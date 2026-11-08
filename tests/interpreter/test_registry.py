import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.context import RunBudget
from app.contracts import ScreeningOutput
from app.services.clinical_trials import ClinicalTrialsClient, RetrievedTrial, parse_trial
from app.validation import validate_screening

PUBLIC = Path(__file__).resolve().parents[2] / "fixtures/public"


def test_real_record_provenance():
    async def check():
        raw = (PUBLIC / "NCT04280705.json").read_bytes()
        metadata = json.loads((PUBLIC / "NCT04280705.provenance.json").read_text())
        assert hashlib.sha256(raw).hexdigest() == metadata["sha256"]
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=raw))
        ) as http:
            service = ClinicalTrialsClient(http, RunBudget.from_settings(Settings(_env_file=None)))
            retrieved = await service.fetch_trial("NCT04280705")
        bundle = parse_trial(retrieved)
        validate_screening(ScreeningOutput(trial_bundle=bundle))
        assert bundle.demographic_rows and bundle.adverse_event_rows
        assert not bundle.is_synthetic
        assert all(r.reported_sex_category is None for r in bundle.adverse_event_rows)
        assert all(
            r.source_locator.location.startswith("$.resultsSection")
            for r in [*bundle.demographic_rows, *bundle.adverse_event_rows]
        )
        stat = retrieved.payload["resultsSection"]["adverseEventsModule"]["seriousEvents"][0][
            "stats"
        ][0]
        row = bundle.adverse_event_rows[0]
        assert row.participants_affected == stat["numAffected"]
        assert row.event_occurrences == stat["numEvents"]
        assert row.group_id == stat["groupId"]

    asyncio.run(check())


def test_no_posted_results_and_invalid_identity(tmp_path):
    async def check():
        payload = {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT00000001",
                    "briefTitle": "Test-only HTTP response",
                }
            },
            "hasResults": False,
        }
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ) as http:
            budget = RunBudget.from_settings(Settings(_env_file=None))
            service = ClinicalTrialsClient(http, budget, cache_dir=tmp_path)
            first = await service.fetch_trial("NCT00000001")
            assert not parse_trial(first).adverse_event_rows
            assert any("No posted results" in s for s in parse_trial(first).limitations)
            second = await service.fetch_trial("NCT00000001")
            assert second == first and budget.used["external_request"] == 1
            replay = ClinicalTrialsClient(http, budget, cache_dir=tmp_path, replay=True)
            assert (await replay.fetch_trial("NCT00000001")).source == first.source
            with pytest.raises(ValueError):
                await replay.fetch_trial("NCT00000002")
            with pytest.raises(ValueError, match="identity"):
                await service.fetch_trial("NCT00000002")
            with pytest.raises(ValidationError):
                await service.fetch_trial("../../bad")
            (tmp_path / "NCT00000001.json").write_text(
                json.dumps({"raw_utf8": "{}", "source": first.source.model_dump(mode="json")})
            )
            with pytest.raises(ValueError, match="hash"):
                await ClinicalTrialsClient(http, budget, cache_dir=tmp_path).fetch_trial(
                    "NCT00000001"
                )

    asyncio.run(check())


def test_search_and_http_failures():
    async def check():
        def reply(request):
            if request.url.path.endswith("/studies"):
                return httpx.Response(
                    200,
                    json={
                        "studies": [
                            {
                                "protocolSection": {
                                    "identificationModule": {
                                        "nctId": "NCT00000001",
                                        "briefTitle": "Test",
                                    }
                                }
                            }
                        ]
                    },
                )
            return httpx.Response(404)

        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
            budget = RunBudget.from_settings(Settings(_env_file=None))
            service = ClinicalTrialsClient(http, budget)
            hits = await service.search_related_trials("test")
            assert hits[0].nct_id == "NCT00000001"
            assert await service.search_related_trials("test") == hits
            assert budget.used["external_request"] == 1
            with pytest.raises(httpx.HTTPStatusError):
                await service.fetch_trial("NCT00000002")
            with pytest.raises(ValueError):
                await service.search_related_trials("test", page_size=100)

    asyncio.run(check())


def test_malformed_record(screening):
    with pytest.raises(ValidationError):
        parse_trial(
            RetrievedTrial(
                payload={"protocolSection": []}, source=screening.trial_bundle.sources[0]
            )
        )


def test_class_denominator_and_identifiable_pk(screening):
    payload = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000001", "briefTitle": "Synthetic parser test"}
        },
        "resultsSection": {
            "baselineCharacteristicsModule": {
                "denoms": [{"units": "Participants", "counts": [{"groupId": "G", "value": "100"}]}],
                "measures": [
                    {
                        "title": "Sex",
                        "paramType": "COUNT_OF_PARTICIPANTS",
                        "classes": [
                            {
                                "denoms": [
                                    {
                                        "units": "Participants",
                                        "counts": [{"groupId": "G", "value": "10"}],
                                    }
                                ],
                                "categories": [
                                    {
                                        "title": "Female",
                                        "measurements": [{"groupId": "G", "value": "4"}],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            "outcomeMeasuresModule": {
                "outcomeMeasures": [
                    {
                        "title": "Plasma Cmax",
                        "paramType": "MEAN",
                        "unitOfMeasure": "ng/mL",
                        "classes": [
                            {
                                "title": "Sex",
                                "categories": [
                                    {
                                        "title": "Female",
                                        "measurements": [
                                            {"groupId": "G", "value": "3.5", "spread": "1"}
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        },
    }
    bundle = parse_trial(RetrievedTrial(payload=payload, source=screening.trial_bundle.sources[0]))
    assert bundle.demographic_rows[0].denominator == 10
    assert bundle.pk_rows[0].value == 3.5
    assert bundle.pk_rows[0].reported_sex_category == "Female"
    assert bundle.pk_rows[0].dose is None
    assert bundle.is_synthetic


def test_wrong_event_count_type_rejected(screening):
    payload = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT00000001",
                "briefTitle": "Synthetic malformed test",
            }
        },
        "resultsSection": {
            "adverseEventsModule": {
                "seriousEvents": [
                    {"term": "Test", "stats": [{"groupId": "G", "numAffected": "20"}]}
                ]
            }
        },
    }
    with pytest.raises(ValidationError):
        parse_trial(RetrievedTrial(payload=payload, source=screening.trial_bundle.sources[0]))
