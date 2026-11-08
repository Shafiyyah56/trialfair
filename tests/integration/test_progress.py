"""Progress snapshots expose emitted work without inventing model completion."""

from datetime import UTC, datetime

from app.contracts import AgentEvent, RunResult
from app.progress import ActiveRunRegistry


def test_progress_tracks_stage_events_and_validated_outputs(screening, fixture_run):
    registry = ActiveRunRegistry()
    registry.start("run-live", includes_interpretation=True)
    event = AgentEvent(
        event_id="event-1",
        run_id="run-live",
        timestamp=datetime.now(UTC),
        agent="interpreter",
        event_type="decision",
        summary="Preparing trial screening in live mode",
    )
    registry.record_event("run-live", event, [])
    active = registry.get("run-live")
    assert active.stage == "Interpreting trial data"
    assert active.events == [event]
    assert active.result_available is False

    registry.screening_ready("run-live", screening)
    screened = registry.get("run-live")
    assert screened.stage == "Investigating safety findings"
    assert screened.screening == screening

    result = RunResult.model_validate(fixture_run).model_copy(update={"run_id": "run-live"})
    result.events = [event]
    registry.finish(result)
    finished = registry.get("run-live")
    assert finished.result_available is True
    assert finished.progress == 1
    assert finished.investigation == result.investigation


def test_progress_snapshots_are_independent_copies():
    registry = ActiveRunRegistry()
    first = registry.start("copy-test", includes_interpretation=False)
    first.stage = "mutated by caller"
    assert registry.get("copy-test").stage == "Preparing investigation"
