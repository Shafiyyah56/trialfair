"""Shared planning reservations, reference validation and actual four-agent UI."""

import asyncio
from time import monotonic

from app.contracts import PlannerReport
from app.orchestrator import investigate_screening
from app.validation import planner_input_limitations


def test_planner_uses_original_deadline_and_cumulative_counters(
    screening,
    investigation,
    context_factory,
    monkeypatch,
):
    from app import orchestrator

    context, _ = context_factory()
    context.budget.limits["model_turn"] = 6
    context.budget.used["model_turn"] = 1
    original_deadline = context.budget.deadline

    async def safety(screening, actual):
        assert actual is context
        assert actual.budget.deadline < original_deadline
        assert actual.budget.limits["model_turn"] == 3
        actual.budget.consume("model_turn")
        return investigation

    async def planner(snapshot, actual):
        assert actual.budget.deadline == original_deadline
        assert actual.budget.limits["model_turn"] == 6
        assert actual.budget.used["model_turn"] == 2
        actual.budget.consume("model_turn")
        return PlannerReport(
            trial_id=snapshot.screening.trial_bundle.trial_id,
            status="partial",
            input_limitations=planner_input_limitations(snapshot),
            is_synthetic=True,
        )

    context.planner_handler = planner
    monkeypatch.setattr(orchestrator, "run_safety", safety)
    result = asyncio.run(investigate_screening(screening, context))
    assert result.planner_report.status == "partial"
    assert context.budget.used["model_turn"] == 3
    assert context.budget.deadline == original_deadline
    assert monotonic() < original_deadline


def test_invalid_planner_report_cannot_remove_upstream_work(
    screening,
    investigation,
    context_factory,
    monkeypatch,
):
    from app import orchestrator

    async def safety(*args):
        return investigation

    async def planner(snapshot, context):
        return PlannerReport(trial_id="wrong-trial", status="partial", is_synthetic=True)

    context, _ = context_factory()
    context.planner_handler = planner
    monkeypatch.setattr(orchestrator, "run_safety", safety)
    result = asyncio.run(investigate_screening(screening, context))
    assert result.screening == screening
    assert result.investigation == investigation
    assert result.planner_report.status == "unavailable"
    assert result.status == "partial"
    assert not result.planner_report.recommendations


def test_live_four_agent_diagram_renders():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string("""
from datetime import datetime, UTC
import streamlit as st
from app.progress import RunProgress
from app.ui.dashboard import render_live_progress
render_live_progress(st, RunProgress(
    run_id="visual-check", status="running", stage="Planning follow-up investigations",
    progress=0.9, active_agent="planner", started_at=datetime.now(UTC), updated_at=datetime.now(UTC)
))
""").run()
    assert not app.exception
    assert any("Planner" in caption.value for caption in app.caption)
    assert len(app.metric) == 4
