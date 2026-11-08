"""Actual nested Agent 2/3 functions with an injected model and synthetic literature."""

import asyncio

from app.agents.evidence import evidence_id_for, run_evidence
from app.api import create_app
from app.config import Settings
from app.contracts import Hypothesis
from app.model_client import ModelResponse, ToolCall
from app.orchestrator import investigate_screening
from app.services.europe_pmc import EuropePMCClient
from tests.evidence.test_agent import CONTRARY, FakeLiterature, calls, draft, item, publication


def test_safety_requests_evidence_and_revises_hypothesis(
    screening,
    investigation,
    context_factory,
):
    responses = [
        ModelResponse(
            tool_calls=[
                ToolCall(
                    call_id="safety-request",
                    name="request_evidence",
                    arguments={
                        "request_id": "research-1",
                        "trial_id": "synthetic-trial-1",
                        "finding_ids": ["finding-gap-1"],
                        "question": "Investigate a possible exposure difference",
                    },
                )
            ]
        ),
        calls(
            ToolCall(
                call_id="search-1", name="search_publications", arguments={"query": "support query"}
            ),
            ToolCall(
                call_id="search-2",
                name="search_publications",
                arguments={"query": "opposing query"},
            ),
        ),
        calls(
            ToolCall(
                call_id="inspect-1",
                name="inspect_publication",
                arguments={"source_id": "lit-support"},
            ),
            ToolCall(
                call_id="inspect-2",
                name="inspect_publication",
                arguments={"source_id": "lit-contrary"},
            ),
        ),
        ModelResponse(),
        draft(item(), item("lit-contrary", CONTRARY, "contradicts", "evidence-2")),
        ModelResponse(text="Hypothesis weakened by contradictory formulation evidence."),
    ]
    investigation.hypotheses = [
        Hypothesis(
            hypothesis_id="hypothesis-1",
            statement="The exposure hypothesis remains formulation-dependent.",
            finding_ids=["finding-gap-1"],
            supporting_evidence_ids=[evidence_id_for("research-1", "evidence-1")],
            contradicting_evidence_ids=[evidence_id_for("research-1", "evidence-2")],
            status="weakened",
        )
    ]
    investigation.evidence_ids = [
        evidence_id_for("research-1", x) for x in ["evidence-1", "evidence-2"]
    ]
    responses.append(ModelResponse(structured_output=investigation.model_dump(mode="json")))
    context, events = context_factory(responses, evidence_handler=run_evidence)
    context.literature = FakeLiterature([[publication()], [publication("lit-contrary", CONTRARY)]])
    result = asyncio.run(investigate_screening(screening, context, mode="replay"))
    assert len(result.evidence_reports) == 1
    assert result.evidence_reports[0].status == "completed"
    assert result.investigation.hypotheses[0].status == "weakened"
    assert result.planner_input.evidence_reports == result.evidence_reports
    assert context.budget.used["model_turn"] == 7
    assert context.budget.used["evidence_request"] == 1
    assert any(event.agent == "evidence" for event in result.events)
    assert not result.errors


def test_runtime_wires_one_shared_budget_into_real_literature_client(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from app import runtime

    monkeypatch.setattr(
        runtime, "GeminiModelClient", lambda **kwargs: SimpleNamespace(model_id="test")
    )
    settings = Settings(
        _env_file=None,
        gemini_api_key="not-a-real-key",
        gemini_model="test",
        data_dir=tmp_path,
        mode="live",
    )
    context = runtime.build_context("test-run", "live", settings=settings)
    assert isinstance(context.literature, EuropePMCClient)
    assert context.literature.budget is context.budget
    assert not tmp_path.joinpath("cache").exists()  # No construction-time filesystem writes.
    assert context.evidence_handler is run_evidence


def test_health_reports_evidence_implementation_without_claiming_full_pipeline():
    from fastapi.testclient import TestClient

    health = TestClient(create_app()).get("/health").json()
    assert health["components"]["evidence"] is True
    assert health["components"]["interpreter"] is False
    assert health["agents_implemented"] is False
