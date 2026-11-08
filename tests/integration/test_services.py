"""Real Agents 1–3 and source adapters; captured HTTP and scripted model, never live."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import runtime
from app.agents.evidence import evidence_id_for
from app.api import create_app
from app.config import Settings
from app.contracts import RunResult
from app.model_client import ModelResponse, ToolCall
from app.services.clinical_trials import ClinicalTrialsClient
from app.services.terminology import SuppliedTerminology
from app.storage import SQLiteRunStore
from tests.evidence.test_europe_pmc import api_record, search_payload

CAPTURE = Path(__file__).resolve().parents[2] / "fixtures/public/NCT04280705.json"
QUOTE = "Test women had higher exposure. No clinical claim is made."


def calls(*commands):
    return ModelResponse(
        tool_calls=[
            ToolCall(call_id=f"call-{i}", name=name, arguments=args)
            for i, (name, args) in enumerate(commands)
        ]
    )


class PipelineModel:
    """Script source selection, inspection and a bounded report; no clinical inference."""

    model_id = "scripted-integration-not-live"

    def __init__(self):
        self.turn = 0
        self.closed = 0

    async def aclose(self):
        self.closed += 1

    async def generate(self, messages, **kwargs):
        self.turn += 1
        if self.turn == 1:
            assert len(messages[-1].content["entries"]) == 20
            return ModelResponse(
                structured_output={
                    "judgements": [
                        {
                            "entry_id": entry["entry_id"],
                            "assertion": "present",
                            "temporality": "unknown",
                            "needs_review": False,
                            "explanation": "Scripted source-term fixture only.",
                        }
                        for entry in messages[-1].content["entries"]
                    ]
                }
            )
        if self.turn == 2:
            overview = messages[-1].content
            self.findings = overview["findings"]
            self.trial_id = overview["trial_id"]
            self.finding_id = self.findings[0]["finding_id"]
            return calls(
                (
                    "request_analysis",
                    {
                        "request_id": "audit-1",
                        "requested_by": "safety",
                        "tool_name": "audit_subgroup_availability",
                        "dataset_ref": overview["registered_dataset_refs"][-1],
                        "parameters": {},
                        "rationale": "Confirm available subgroup data.",
                        "related_finding_ids": [self.finding_id],
                    },
                ),
                (
                    "request_evidence",
                    {
                        "request_id": "research-1",
                        "trial_id": self.trial_id,
                        "finding_ids": [self.finding_id],
                        "question": "Investigate supporting and opposing sex-specific evidence.",
                    },
                ),
            )
        if self.turn == 3:
            assert {"search_related_trials", "inspect_trial_record"} <= {
                tool.name for tool in kwargs["tools"]
            }
            return calls(
                ("search_publications", {"query": "test sex exposure"}),
                ("search_publications", {"query": "test no sex difference"}),
                ("search_related_trials", {"query": self.trial_id}),
            )
        if self.turn == 4:
            return calls(
                ("inspect_publication", {"source_id": "999999999"}),
                ("inspect_trial_record", {"nct_id": self.trial_id}),
            )
        if self.turn == 5:
            return ModelResponse(text="Source inspection complete.")
        if self.turn == 6:
            # Bind the claim to the exact packet actually returned by the source tool.
            packets = messages[-1].content["inspected_sources"]
            packet = next(p for p in packets if p["source"]["source_type"] == "publication")
            return ModelResponse(
                structured_output={
                    "evidence_items": [
                        {
                            "evidence_id": "item-1",
                            "source_id": packet["source"]["source_id"],
                            "finding_ids": [self.finding_id],
                            "claim": "Transport test only.",
                            "relation": "background",
                            "location": packet["location"],
                            "excerpt": QUOTE,
                            "relevance": "Synthetic HTTP test prose only.",
                            "limitations": ["No clinical inference; abstract-only test."],
                        }
                    ],
                    "status": "completed",
                    "unresolved_questions": [],
                    "analysis_suggestions": [],
                    "limitations": [],
                }
            )
        if self.turn == 7:
            return ModelResponse(text="Research inspected; retain source limitations.")
        assert self.turn == 8
        eid = evidence_id_for("research-1", "item-1")
        return ModelResponse(
            structured_output={
                "trial_id": self.trial_id,
                "status": "completed",
                "evidence_ids": [eid],
                "assessed_findings": [
                    {
                        "finding_id": f["finding_id"],
                        "conclusion": "Offline integration review only.",
                        "priority": "low",
                        "rationale": "Verify data flow without making a clinical conclusion.",
                        "evidence_ids": [eid] if f["finding_id"] == self.finding_id else [],
                    }
                    for f in self.findings
                ],
            }
        )


def test_api_connects_all_agents_sources_statistics_and_storage(monkeypatch, tmp_path):
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "clinicaltrials.gov":
            if request.url.path.endswith("/NCT04280705"):
                return httpx.Response(200, content=CAPTURE.read_bytes())
            return httpx.Response(
                200,
                json={
                    "studies": [
                        {
                            "protocolSection": {
                                "identificationModule": {
                                    "nctId": "NCT04280705",
                                    "briefTitle": "Capture",
                                }
                            }
                        }
                    ]
                },
            )
        assert request.url.host == "www.ebi.ac.uk"
        return httpx.Response(200, json=search_payload([api_record(isOpenAccess="N")]))

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    model = PipelineModel()
    monkeypatch.setattr(runtime.httpx, "AsyncClient", lambda: http_client)
    monkeypatch.setattr(runtime, "GeminiModelClient", lambda **kwargs: model)
    settings = Settings(
        _env_file=None,
        gemini_api_key="test-only",
        gemini_model="test",
        data_dir=tmp_path,
        mode="live",
    )
    contexts = []

    def factory(run_id, mode):
        context = runtime.build_context(run_id, mode, settings=settings)
        contexts.append(context)
        return context

    client = TestClient(
        create_app(context_factory=factory, store=SQLiteRunStore(tmp_path / "runs.sqlite"))
    )
    response = client.post("/runs", json={"nct_id": "NCT04280705", "mode": "live"})
    assert response.status_code == 200
    result = RunResult.model_validate(response.json())
    assert not result.errors
    assert result.screening is not None
    assert result.screening.analyses
    assert result.screening.trial_bundle.availability.sex_stratified_ae != "available"
    assert len(result.evidence_reports) == 1
    assert len(result.evidence_reports[0].evidence_items) == 1
    assert result.investigation.status == "completed"
    # The real capture exceeds the configured interpreter text cap: retain partial status.
    assert result.status == "partial"
    assert any("Interpretation limited" in x for x in result.screening.trial_bundle.limitations)
    assert {event.agent for event in result.events} >= {"interpreter", "safety", "evidence"}
    context = contexts[0]
    assert isinstance(context.registry, ClinicalTrialsClient)
    assert isinstance(context.terminology, SuppliedTerminology)
    assert context.registry.budget is context.literature.budget is context.budget
    assert context.budget.used == {
        "external_request": 4,
        "model_turn": 8,
        "additional_analysis": 1,
        "evidence_request": 1,
    }
    assert len(context.additional_analyses) == 1
    added = context.additional_analyses[0].analysis_id
    assert sum(a.analysis_id == added for a in result.screening.analyses) == 1
    assert len([r for r in requests if r.url.path.endswith("/NCT04280705")]) == 1
    assert result.planner_input.evidence_reports == result.evidence_reports
    saved = client.get(f"/runs/{result.run_id}").json()
    assert saved["evidence_reports"] == response.json()["evidence_reports"]
    assert http_client.is_closed and model.closed == 1


def test_cleanup_is_idempotent_and_continues_after_resource_failure(context_factory):
    context, _ = context_factory()
    closed = []

    async def broken():
        closed.append("http")
        raise RuntimeError("Injected cleanup failure")

    async def close_model():
        closed.append("model")

    context.resource_closers.append(broken)
    context.model = SimpleNamespace(model_id="test", aclose=close_model)

    async def scenario():
        await context.aclose()
        await context.aclose()

    asyncio.run(scenario())
    assert closed == ["http", "model"]


def test_registry_outage_preserves_failure_and_closes_resources(monkeypatch, tmp_path):
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    )
    model = PipelineModel()
    monkeypatch.setattr(runtime.httpx, "AsyncClient", lambda: http_client)
    monkeypatch.setattr(runtime, "GeminiModelClient", lambda **kwargs: model)
    settings = Settings(
        _env_file=None, gemini_api_key="test-only", gemini_model="test", data_dir=tmp_path
    )
    client = TestClient(
        create_app(
            context_factory=lambda run_id, mode: runtime.build_context(
                run_id, mode, settings=settings
            ),
            store=SQLiteRunStore(tmp_path / "runs.sqlite"),
        )
    )
    response = client.post("/runs", json={"nct_id": "NCT04280705"})
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["screening"] is None
    assert response.json()["errors"]
    assert model.turn == 0  # Never invent trial data or spend model calls after fetch failure.
    assert http_client.is_closed and model.closed == 1


def test_injected_services_remain_caller_owned(monkeypatch, tmp_path):
    model = PipelineModel()
    monkeypatch.setattr(runtime, "GeminiModelClient", lambda **kwargs: model)
    service = SimpleNamespace()
    services = runtime.RuntimeServices(service, service, service)
    context = runtime.build_context(
        "injected",
        "live",
        services=services,
        settings=Settings(
            _env_file=None, gemini_api_key="test-only", gemini_model="test", data_dir=tmp_path
        ),
    )
    assert context.registry is service
    assert not context.resource_closers
    asyncio.run(context.aclose())
    assert model.closed == 1


@pytest.mark.parametrize("status", ["partial", "unavailable"])
def test_unfinished_evidence_prevents_completed_run(
    status,
    screening,
    investigation,
    context_factory,
    monkeypatch,
):
    from app import orchestrator
    from app.contracts import EvidenceReport

    async def investigate(screening, context):
        context.evidence_reports.append(EvidenceReport(request_id="unfinished", status=status))
        return investigation.model_copy(update={"status": "completed"})

    monkeypatch.setattr(orchestrator, "run_safety", investigate)
    context, _ = context_factory()
    result = asyncio.run(orchestrator.investigate_screening(screening, context))
    assert result.status == "partial"
    assert result.planner_input is not None


@pytest.mark.parametrize("case", ["review-mapping", "failed-followup", "source-gap"])
def test_interpretation_review_is_distinct_from_scientific_missing_data(
    case,
    screening,
    investigation,
    context_factory,
    monkeypatch,
):
    from app import orchestrator
    from app.contracts import SymptomMapping

    if case == "review-mapping":
        screening.symptom_mappings.append(
            SymptomMapping(
                mapping_id="unresolved",
                original_text="Unclear symptom",
                assertion="uncertain",
                temporality="unknown",
                needs_review=True,
                explanation="Source wording needs human review.",
                source_locator=screening.analyses[0].source_locators[0],
            )
        )
    elif case == "failed-followup":
        screening.trial_bundle.limitations.append(
            "Follow-up interpretation of flagged entries failed; they remain flagged."
        )
    else:
        assert screening.trial_bundle.availability.sex_stratified_ae == "missing"

    async def investigate(screening, context):
        return investigation.model_copy(update={"status": "completed"})

    monkeypatch.setattr(orchestrator, "run_safety", investigate)
    context, _ = context_factory()
    result = asyncio.run(orchestrator.investigate_screening(screening, context))
    assert result.status == ("completed" if case == "source-gap" else "partial")
