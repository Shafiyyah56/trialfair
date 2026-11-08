"""Regression cases from the pre-merge audit; all sources/models are injected."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from google.genai.errors import ClientError, ServerError

from app.agents.interpreter import run_interpreter
from app.agents.safety import dispatch_tool, merged_screening
from app.contracts import (
    AnalysisRequest,
    FindingAssessment,
    InvestigationReport,
    NarrativeEntry,
    PlannerInput,
    ScreeningOutput,
    SourceRecord,
    TrialBundle,
    TrialInput,
)
from app.model_client import ModelResponse, ToolCall
from app.orchestrator import run_trial
from app.services.clinical_trials import ClinicalTrialsClient, RetrievedTrial, parse_trial
from app.services.statistics import audit_subgroup_availability, execute_analysis
from app.validation import validate_planner_input, validate_screening

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def bundle():
    return TrialBundle.model_validate_json(
        (FIXTURES / "synthetic/interpreter_counts.bundle.json").read_text()
    )


@pytest.mark.parametrize(
    "error",
    [
        ClientError(429, {"error": {"message": "injected-secret-provider-message"}}),
        ServerError(503, {"error": {"message": "injected-secret-provider-message"}}),
        httpx.ConnectError("injected-secret-provider-message"),
        httpx.ReadTimeout("injected-secret-provider-message"),
    ],
)
@pytest.mark.parametrize("stage", ["first-pass", "follow-up"])
def test_provider_failures_preserve_screening(context_factory, error, stage):
    flagged = {
        "judgements": [
            {
                "entry_id": "t1",
                "assertion": "uncertain",
                "temporality": "unknown",
                "needs_review": True,
                "explanation": "Flagged",
            }
        ]
    }
    responses = (
        [error] if stage == "first-pass" else [ModelResponse(structured_output=flagged), error]
    )
    context, events = context_factory(responses)
    context.datasets["input"] = bundle()
    output = asyncio.run(
        run_interpreter(TrialInput(dataset_refs=["input"], mode="replay"), context)
    )
    validate_screening(output)
    assert len(output.analyses) == 4
    assert any("risk_difference" in a.results for a in output.analyses)
    assert all(m.needs_review for m in output.symptom_mappings)
    expected = "Interpretation incomplete" if stage == "first-pass" else "Follow-up"
    assert any(expected in s for s in output.trial_bundle.limitations)
    assert "injected-secret" not in output.model_dump_json()
    assert "injected-secret" not in " ".join(e.summary for e in events)


def test_task_cancellation_is_not_swallowed(context_factory):
    async def check():
        context, _ = context_factory()
        context.datasets["input"] = bundle()
        entered = asyncio.Event()

        class HangingModel:
            async def generate(self, *args, **kwargs):
                entered.set()
                await asyncio.Event().wait()

        context.model = HangingModel()
        task = asyncio.create_task(
            run_interpreter(TrialInput(dataset_refs=["input"], mode="replay"), context)
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(check())


def test_internal_entry_namespaces_do_not_drop_narratives(context_factory):
    context, _ = context_factory([RuntimeError("Injected model unavailability")])
    data = bundle()
    data.narrative_entries = [
        NarrativeEntry(
            entry_id=f"ae:{data.adverse_event_rows[0].row_id}",
            text="No vomiting was reported",
            locator={"source_id": data.sources[0].source_id, "location": "synthetic.narrative"},
        )
    ]
    context.datasets["input"] = data
    output = asyncio.run(
        run_interpreter(TrialInput(dataset_refs=["input"], mode="replay"), context)
    )
    assert len(output.symptom_mappings) == 3
    assert any(m.original_text == "No vomiting was reported" for m in output.symptom_mappings)
    assert sum(m.original_text == "Dizziness" for m in output.symptom_mappings) == 2


@pytest.mark.parametrize(
    ("case", "state"),
    [
        ("one-sex", "incomplete"),
        ("different-arm", "incompatible"),
        ("different-window", "incompatible"),
        ("occurrences-only", "incompatible"),
        ("compatible", "available"),
        ("not-extracted", "not_assessed"),
    ],
)
def test_audit_checks_actual_comparison_preconditions(case, state):
    data = bundle()
    if case == "one-sex":
        data.adverse_event_rows = data.adverse_event_rows[:1]
    elif case == "different-arm":
        data.adverse_event_rows[1].group_id = "another-arm"
    elif case == "different-window":
        data.adverse_event_rows[1].reporting_window = "Day 99"
    elif case == "occurrences-only":
        data.adverse_event_rows[1].participants_affected = None
        data.adverse_event_rows[1].event_occurrences = 100
    elif case == "not-extracted":
        data.availability.sex_stratified_ae = "not_assessed"
        for row in data.adverse_event_rows:
            row.reported_sex_category = None
    result, _ = audit_subgroup_availability(data, [])
    ae = result["comparison_availability"]["adverse_events"]
    assert ae["status"] == state
    assert bool(ae["compatible_row_pairs"]) == (state == "available")
    assert any("AE" in s for s in result["missing_fields"]) == (state != "available")


def test_not_applicable_pk_is_not_reported_missing():
    data = bundle()
    data.availability.sex_stratified_pk = "not_applicable"
    result, _ = audit_subgroup_availability(data, [])
    assert not any("PK" in s for s in result["missing_fields"])


def test_unassessed_source_finding_does_not_claim_absence(context_factory):
    context, _ = context_factory([RuntimeError("Injected model unavailability")])
    data = bundle()
    data.availability.sex_stratified_ae = "not_assessed"
    for row in data.adverse_event_rows:
        row.reported_sex_category = None
    context.datasets["input"] = data
    result = asyncio.run(
        run_interpreter(TrialInput(dataset_refs=["input"], mode="replay"), context)
    )
    gap = next(f for f in result.findings if f.finding_type == "evidence_gap")
    assert "does not establish absence" in gap.description
    assert "record lacks" not in gap.description


def pk_payload(*, split=True, class_denominator=False):
    denom = [{"units": "Participants", "counts": [{"groupId": "G", "value": "100"}]}]
    cls = {
        "title": "Sex" if split else "Overall",
        "categories": [
            {
                "title": sex,
                "measurements": [
                    {
                        "groupId": "G",
                        "value": "3.5",
                        "spread": "1.2",
                        "lowerLimit": "1.0",
                        "upperLimit": "6.0",
                    }
                ],
            }
            for sex in (["Female", "Male"] if split else ["Overall"])
        ],
    }
    outcome = {
        "title": "Plasma Cmax",
        "paramType": "MEAN",
        "unitOfMeasure": "ng/mL",
        "dispersionType": "95% Confidence Interval",
        "classes": [cls],
    }
    (cls if class_denominator else outcome)["denoms"] = denom
    return {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000001", "briefTitle": "Synthetic PK audit"}
        },
        "resultsSection": {"outcomeMeasuresModule": {"outcomeMeasures": [outcome]}},
    }


@pytest.mark.parametrize("class_denominator", [False, True])
def test_pk_group_counts_never_become_subgroup_sizes(class_denominator):
    parsed = parse_trial(
        RetrievedTrial(
            payload=pk_payload(class_denominator=class_denominator), source=bundle().sources[0]
        )
    )
    assert len(parsed.pk_rows) == 2
    assert all(row.sample_size is None for row in parsed.pk_rows)
    assert any("sample size withheld" in s for s in parsed.limitations)
    for row in parsed.pk_rows:
        uncertainty = json.loads(row.variability)
        assert uncertainty == {
            "dispersionType": "95% Confidence Interval",
            "spread": "1.2",
            "lowerLimit": "1.0",
            "upperLimit": "6.0",
        }


def test_pk_unsplit_reported_group_size_is_preserved():
    parsed = parse_trial(
        RetrievedTrial(payload=pk_payload(split=False), source=bundle().sources[0])
    )
    assert parsed.pk_rows[0].sample_size == 100


def capture_source():
    metadata = json.loads((FIXTURES / "public/NCT04280705.provenance.json").read_text())
    return SourceRecord(
        source_id="captured-real",
        source_type="trial_registry",
        title="Captured registry record",
        external_id="NCT04280705",
        url=metadata["url"],
        content_hash=metadata["sha256"],
        retrieved_at=metadata["retrieved_at"],
        access_level="full_text",
        is_synthetic=False,
    )


def test_replay_default_live_client_never_issues_http(context_factory):
    async def check():
        context, _ = context_factory([RuntimeError("Injected model unavailability")])
        attempts = []

        def forbidden(request):
            attempts.append(request)
            raise AssertionError("Replay attempted HTTP")

        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
            context.registry = ClinicalTrialsClient(http, context.budget)
            with pytest.raises(ValueError, match="No captured"):
                await run_interpreter(TrialInput(nct_id="NCT04280705", mode="replay"), context)
            context.registry.load_capture(
                (FIXTURES / "public/NCT04280705.json").read_bytes(), capture_source()
            )
            result = await run_interpreter(TrialInput(nct_id="NCT04280705", mode="replay"), context)
            validate_screening(result)
            assert result.trial_bundle.sources[0] == capture_source()
            assert not attempts and context.budget.used.get("external_request", 0) == 0

    asyncio.run(check())


def test_replay_rejects_service_without_cache_only_entrypoint(context_factory):
    async def check():
        context, _ = context_factory()

        class LiveOnly:
            async def fetch_trial(self, nct_id):
                pytest.fail("Live-only service must never be invoked in replay")

        context.registry = LiveOnly()
        with pytest.raises(ValueError, match="cache-only"):
            await run_interpreter(TrialInput(nct_id="NCT04280705", mode="replay"), context)

    asyncio.run(check())


def test_real_agent2_dispatch_accepts_agent1_reanalysis(context_factory):
    async def check():
        context, _ = context_factory(analysis_handler=execute_analysis)
        data = bundle()
        context.datasets["input"] = data
        screening = ScreeningOutput(trial_bundle=data)
        request = AnalysisRequest(
            request_id="regression",
            requested_by="safety",
            tool_name="compare_adverse_event_rates",
            dataset_ref="input",
            rationale="Offline audit",
            parameters={"row_ids": [r.row_id for r in data.adverse_event_rows]},
        )
        result = await dispatch_tool(
            ToolCall(
                call_id="call", name="request_analysis", arguments=request.model_dump(mode="json")
            ),
            screening,
            context,
        )
        assert result["status"] == "completed"
        assert result["results"]["risk_difference"] == pytest.approx(0.1)
        assert len(context.additional_analyses) == 1
        validate_planner_input(
            PlannerInput(
                screening=merged_screening(screening, context),
                investigation=InvestigationReport(trial_id=data.trial_id, status="partial"),
                evidence_reports=[],
            )
        )

    asyncio.run(check())


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="RunResult status is owned by unchanged Agent 2/orchestrator; "
    "ScreeningOutput has no status field. Requires integrator fix.",
)
def test_incomplete_interpretation_must_make_run_partial(context_factory):
    class MixedModel:
        model_id = "offline-regression-model"

        def __init__(self):
            self.turn = 0

        async def generate(self, messages, **kwargs):
            self.turn += 1
            if self.turn == 1:
                raise RuntimeError("Injected interpreter failure")
            if self.turn == 2:
                overview = messages[-1].content
                self.finding = overview["findings"][0]
                self.trial_id = overview["trial_id"]
                return ModelResponse(
                    tool_calls=[
                        ToolCall(
                            call_id="inspect",
                            name="inspect_finding",
                            arguments={"finding_id": self.finding["finding_id"]},
                        )
                    ]
                )
            if self.turn == 3:
                return ModelResponse(text="Inspection complete")
            return ModelResponse(
                structured_output=InvestigationReport(
                    trial_id=self.trial_id,
                    status="completed",
                    assessed_findings=[
                        FindingAssessment(
                            finding_id=self.finding["finding_id"],
                            conclusion="Offline fixture review",
                            priority="low",
                            rationale="Synthetic regression fixture",
                        )
                    ],
                ).model_dump(mode="json")
            )

    context, _ = context_factory()
    context.model = MixedModel()
    context.datasets["input"] = bundle()
    result = asyncio.run(run_trial(TrialInput(dataset_refs=["input"], mode="replay"), context))
    if result.screening is None or not any(
        "Interpretation incomplete" in s for s in result.screening.trial_bundle.limitations
    ):
        raise RuntimeError("Regression setup did not retain incomplete screening")
    assert result.status == "partial"


def test_provider_failure_keeps_screening_through_real_orchestrator(context_factory):
    context, _ = context_factory(
        [
            ClientError(429, {"error": {"message": "Injected provider failure"}}),
            RuntimeError("Injected investigator unavailability"),
        ]
    )
    context.datasets["input"] = bundle()
    result = asyncio.run(run_trial(TrialInput(dataset_refs=["input"], mode="replay"), context))
    assert result.status == "partial"
    assert result.screening is not None
    assert any("risk_difference" in a.results for a in result.screening.analyses)
    assert not result.errors


def test_registered_capture_rejects_changed_bytes(context_factory):
    context, _ = context_factory()

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: pytest.fail("Capture registration must not fetch")
            )
        ) as http:
            service = ClinicalTrialsClient(http, context.budget)
            with pytest.raises(ValueError, match="hash"):
                service.load_capture(b"{}", capture_source())

    asyncio.run(check())


def test_pk_unlabelled_sex_category_does_not_inherit_group_size():
    payload = pk_payload()
    category = payload["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"][0]["classes"][
        0
    ]["categories"][0]
    category.pop("title")
    parsed = parse_trial(RetrievedTrial(payload=payload, source=bundle().sources[0]))
    assert parsed.pk_rows[0].reported_sex_category is None
    assert parsed.pk_rows[0].sample_size is None
