"""Integration tests with injected services: no real clinical research or paid calls."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app import orchestrator
from app.api import create_app
from app.contracts import RunResult, TrialInput
from app.model_client import ModelResponse, ToolCall
from app.orchestrator import investigate_screening
from app.storage import SQLiteRunStore


def responses(final_response):
    return [
        ModelResponse(
            tool_calls=[
                ToolCall(
                    call_id="call-1",
                    name="inspect_finding",
                    arguments={"finding_id": "finding-gap-1"},
                )
            ]
        ),
        ModelResponse(),
        final_response,
    ]


def test_prepared_screening_produces_planner_input(screening, context_factory, final_response):
    context, _ = context_factory(responses(final_response))
    result = asyncio.run(investigate_screening(screening, context, mode="replay"))
    assert result.mode == "replay"
    assert result.screening.trial_bundle.is_synthetic
    assert result.planner_input.investigation == result.investigation
    assert result.events[0].event_type == "tool_call"
    assert result.model_id == "test-scripted-not-live"
    assert result.duration_ms > 0


def test_full_pipeline_calls_injected_interpreter(
    screening,
    context_factory,
    final_response,
    monkeypatch,
):
    async def interpret(trial_input, context):
        assert trial_input.nct_id == "NCT12345678"
        return screening

    monkeypatch.setattr(orchestrator, "run_interpreter", interpret)
    context, _ = context_factory(responses(final_response))
    result = asyncio.run(
        orchestrator.run_trial(
            TrialInput(nct_id="NCT12345678", mode="replay"),
            context,
        )
    )
    assert result.screening == screening
    assert result.planner_input is not None
    assert not result.errors


def test_unimplemented_interpreter_is_not_faked(context_factory):
    context, _ = context_factory()
    result = asyncio.run(orchestrator.run_trial(TrialInput(nct_id="NCT12345678"), context))
    assert result.status == "failed"
    assert result.screening is None
    assert "not yet implemented" in result.errors[0]
    assert not context.model.calls


def test_api_runs_and_retrieves_validated_output(
    screening,
    context_factory,
    final_response,
    tmp_path,
):
    def make_context(run_id, mode):
        context, _ = context_factory(responses(final_response))
        context.run_id = run_id
        return context

    store = SQLiteRunStore(tmp_path / "runs.sqlite")
    client = TestClient(create_app(context_factory=make_context, store=store))
    response = client.post(
        "/investigations",
        json={
            "screening": screening.model_dump(mode="json"),
            "mode": "replay",
        },
    )
    assert response.status_code == 200
    result = RunResult.model_validate(response.json())
    saved = client.get(f"/runs/{result.run_id}")
    assert saved.status_code == 200
    assert saved.json()["run_id"] == result.run_id
    assert saved.json()["planner_input"] is not None
    assert client.get("/runs/nonexistent").status_code == 404
    assert client.post("/investigations", json={"screening": {}}).status_code == 422


def test_invalid_provenance_cannot_become_a_completed_run(screening, context_factory):
    screening.findings[0].analysis_ids = ["invented"]
    context, _ = context_factory()
    result = asyncio.run(investigate_screening(screening, context))
    assert result.status == "failed"
    assert result.screening is None
    assert not context.model.calls


def test_sqlite_concurrent_writes_and_sql_like_ids(fixture_run, tmp_path):
    store = SQLiteRunStore(tmp_path / "nested" / "runs.sqlite")
    assert not store.path.exists()
    assert store.get("missing") is None
    assert not store.path.exists()
    base = RunResult.model_validate(fixture_run)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda i: store.save(base.model_copy(update={"run_id": f"run-{i}"})),
                range(8),
            )
        )
    assert len(results) == 8
    assert store.get("run-7").run_id == "run-7"
    assert store.get("' OR 1=1 --") is None


def test_persisted_narratives_are_removed(fixture_run, tmp_path):
    from app.contracts import NarrativeEntry

    result = RunResult.model_validate(fixture_run)
    locator = result.screening.analyses[0].source_locators[0]
    narrative = NarrativeEntry(
        entry_id="sensitive", text="Private source narrative", locator=locator
    )
    result.screening.trial_bundle.narrative_entries = [narrative]
    result.planner_input.screening.trial_bundle.narrative_entries = [narrative]
    store = SQLiteRunStore(tmp_path / "runs.sqlite")
    store.save(result)
    saved = store.get(result.run_id)
    assert not saved.screening.trial_bundle.narrative_entries
    assert "Private source narrative" not in saved.model_dump_json()
    assert result.screening.trial_bundle.narrative_entries  # Original not mutated.
