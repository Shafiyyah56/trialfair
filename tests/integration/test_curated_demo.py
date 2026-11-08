"""Curated evidence is real, explicit, trial-bound and uses standard grounding checks."""

import asyncio

import pytest

from app.contracts import EvidenceRequest
from app.demo import DEMO_TRIAL, run_curated_evidence, source_review_fallback


def test_curated_review_retains_three_real_sources_and_flags_selection(context_factory):
    context, events = context_factory()
    report = asyncio.run(
        run_curated_evidence(
            EvidenceRequest(
                request_id="curated-demo",
                trial_id=DEMO_TRIAL,
                finding_ids=["finding-gap-1"],
                question="Inspect curated sources",
            ),
            context,
        )
    )
    assert len(report.evidence_items) == len(report.sources) == 3
    assert not report.searches  # Never represent a packaged source lookup as an internet search.
    assert report.status == "partial"
    assert all(not source.is_synthetic for source in report.sources)
    assert any("Curated demonstration" in line for line in report.limitations)
    assert all(len(item.source_locator.excerpt.split()) <= 25 for item in report.evidence_items)
    assert all(item.source_id == item.source_locator.source_id for item in report.evidence_items)
    assert sum(event.event_type == "tool_result" for event in events) == 3
    assert context.budget.used == {}  # No model/source HTTP calls were invented.
    animal = next(item for item in report.evidence_items if "guinea-pig" in item.claim)
    assert animal.relation == "background"
    assert any("Animal" in line for line in animal.limitations)


def test_curated_profile_rejects_unrelated_trials(context_factory):
    context, _ = context_factory()
    with pytest.raises(ValueError, match="only supports"):
        asyncio.run(
            run_curated_evidence(
                EvidenceRequest(
                    request_id="wrong",
                    trial_id="NCT01234567",
                    finding_ids=["finding-gap-1"],
                    question="Wrong trial",
                ),
                context,
            )
        )


def test_demo_fallback_preserves_findings_without_claiming_model_success(
    screening,
    investigation,
    context_factory,
):
    context, _ = context_factory()
    result = source_review_fallback(screening, context, investigation)
    assert result.status == "partial"
    assert result.assessed_findings[0].conclusion == screening.findings[0].description
    assert any("Rules-based assessment fallback" in line for line in result.limitations)


def test_demo_async_api_reaches_cited_persisted_report(context_factory, tmp_path):
    import time

    import httpx
    from fastapi.testclient import TestClient

    from app.api import create_app
    from app.contracts import InvestigationReport, RunResult
    from app.model_client import ModelResponse, ToolCall
    from app.services.clinical_trials import ClinicalTrialsClient
    from app.services.statistics import execute_analysis
    from app.storage import SQLiteRunStore

    class DemoModel:
        model_id = "scripted-demo-integration-not-live"

        def __init__(self):
            self.turn = 0

        async def generate(self, messages, **kwargs):
            self.turn += 1
            if self.turn == 1:
                return ModelResponse(
                    structured_output={
                        "judgements": [
                            {
                                "entry_id": entry["entry_id"],
                                "assertion": "present",
                                "temporality": "unknown",
                                "needs_review": False,
                                "explanation": "Offline fixture interpretation.",
                            }
                            for entry in messages[-1].content["entries"]
                        ]
                    }
                )
            if self.turn == 2:
                overview = messages[-1].content
                self.trial_id = overview["trial_id"]
                self.finding_id = overview["findings"][0]["finding_id"]
                assert len(overview["available_evidence_reports"][0]["evidence_items"]) == 3
                return ModelResponse(
                    tool_calls=[
                        ToolCall(
                            call_id="inspect",
                            name="inspect_finding",
                            arguments={"finding_id": self.finding_id},
                        )
                    ]
                )
            if self.turn == 3:
                return ModelResponse(text="Inspection complete.")
            return ModelResponse(
                structured_output=InvestigationReport(
                    trial_id=self.trial_id,
                    status="partial",
                    unresolved_questions=["Human review of missing subgroup evidence is required."],
                ).model_dump(mode="json")
            )

    model = DemoModel()
    contexts = []

    def factory(run_id, mode):
        context, _ = context_factory()
        context.run_id = run_id
        context.settings = context.settings.model_copy(update={"mode": "live"})
        context.model = model
        http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: pytest.fail("Curated demo must use captured sources")
            )
        )
        context.registry = ClinicalTrialsClient(http_client, context.budget)
        context.analysis_handler = execute_analysis
        context.resource_closers.append(http_client.aclose)
        contexts.append(context)
        return context

    application = create_app(
        context_factory=factory, store=SQLiteRunStore(tmp_path / "runs.sqlite")
    )
    with TestClient(application) as client:
        response = client.post("/demo/runs/async", json={"nct_id": DEMO_TRIAL})
        assert response.status_code == 202
        progress_url = response.json()["progress_url"]
        for _ in range(50):
            progress = client.get(progress_url).json()
            if progress["result_available"]:
                break
            time.sleep(0.01)
        assert progress["result_available"]
        result = RunResult.model_validate(client.get(f"/runs/{response.json()['run_id']}").json())
        assert result.screening.trial_bundle.trial_id == DEMO_TRIAL
        assert len(result.evidence_reports[0].evidence_items) == 3
        assert result.planner_input is not None
        assert (
            result.investigation.assessed_findings
        )  # Explicit rules fallback if model is incomplete.
        assert {event.agent for event in result.events} >= {"interpreter", "safety", "evidence"}
        assert any(
            "Curated demonstration" in line for line in result.screening.trial_bundle.limitations
        )
        assert client.post("/demo/runs/async", json={"nct_id": "NCT01234567"}).status_code == 422
    assert contexts[0]._closed
