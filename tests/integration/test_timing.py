"""Short injected delays verify partial-result preservation without paid/network calls."""

import asyncio
from types import SimpleNamespace

from app.agents.evidence import run_evidence
from app.agents.interpreter import run_interpreter
from app.config import Settings
from app.contracts import TrialInput
from app.model_client import ModelResponse
from app.orchestrator import investigate_screening
from tests.evidence.test_agent import FakeLiterature, call, calls, publication, request
from tests.interpreter.test_regressions import bundle


def test_evidence_time_limit_retains_searched_and_inspected_sources(context_factory):
    context, _ = context_factory(
        [
            calls(call("search_publications", query="first query")),
            calls(
                call("inspect_publication", source_id="lit-support"),
                call("search_publications", query="opposing query"),
            ),
        ],
        settings=Settings(_env_file=None, run_timeout_seconds=0.1),
    )
    cancelled = []

    class SlowSecondSearch(FakeLiterature):
        async def search_publications(self, query, *, page_size=5):
            if query == "opposing query":
                try:
                    await asyncio.sleep(10)
                finally:
                    cancelled.append(True)
            return await super().search_publications(query, page_size=page_size)

    context.literature = SlowSecondSearch([[publication()]])
    report = asyncio.run(run_evidence(request(), context))
    assert cancelled
    assert report.status == "partial"
    assert len(report.sources) == 1
    assert len(report.searches) == 2
    assert not report.evidence_items  # Inspected text is not an automatically synthesised claim.
    assert any("time reserved" in limitation for limitation in report.limitations)
    assert context.budget.remaining_seconds() > 0
    assert context.budget.used["model_turn"] == 2


def test_interpretation_time_limit_keeps_deterministic_screening(context_factory):
    context, _ = context_factory(
        settings=Settings(_env_file=None, mode="replay", run_timeout_seconds=0.1)
    )
    data = bundle()
    context.datasets["input"] = data
    cancelled = []

    async def slow_model(*args, **kwargs):
        try:
            await asyncio.sleep(10)
            return ModelResponse()
        finally:
            cancelled.append(True)

    context.model = SimpleNamespace(model_id="slow-test", generate=slow_model)
    output = asyncio.run(
        run_interpreter(TrialInput(dataset_refs=["input"], mode="replay"), context)
    )
    assert cancelled
    assert output.trial_bundle.adverse_event_rows == data.adverse_event_rows
    assert any("risk_difference" in analysis.results for analysis in output.analyses)
    assert output.symptom_mappings and all(m.needs_review for m in output.symptom_mappings)
    assert context.budget.remaining_seconds() > 0


def test_outer_deadline_keeps_an_explicit_unassessed_investigation(
    screening,
    context_factory,
    monkeypatch,
):
    from app import orchestrator

    async def slow_safety(*args):
        await asyncio.sleep(10)

    monkeypatch.setattr(orchestrator, "run_safety", slow_safety)
    context, _ = context_factory(settings=Settings(_env_file=None, run_timeout_seconds=0.02))
    result = asyncio.run(investigate_screening(screening, context))
    assert result.status == "partial"
    assert result.screening is not None
    assert result.investigation.status == "partial"
    assert not result.investigation.assessed_findings
    assert result.planner_input is not None
    assert any("deadline exhausted" in error for error in result.errors)
