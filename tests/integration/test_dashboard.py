"""Render the actual Streamlit UI with a labelled synthetic saved-run example."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_dashboard_imports_from_outside_checkout_without_pythonpath(tmp_path):
    import subprocess
    import sys

    dashboard = Path(__file__).resolve().parents[2] / "app/ui/dashboard.py"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            f"import runpy; runpy.run_path({str(dashboard)!r}, run_name='import_check')",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_saved_run_review_renders_without_live_execution(fixture_run):
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[2] / "app/ui/dashboard.py"), default_timeout=10
    )
    app.session_state["result"] = fixture_run
    app.session_state["saved_review"] = True
    app.run()
    assert not app.exception
    assert any("simulated" in item.value for item in app.warning)
    assert any("Saved result review" in item.value for item in app.caption)
    assert any("synthetic-trial-1" in item.value for item in app.caption)


def test_saved_four_agent_report_renders_planner_actions():
    from app.contracts import PlannerInput, PlannerReport, RunResult
    from app.validation import validate_run

    root = Path(__file__).resolve().parents[2]
    snapshot = PlannerInput.model_validate_json(
        (root / "fixtures/synthetic/planner_complete_input.json").read_text()
    )
    plan = PlannerReport.model_validate_json(
        (root / "fixtures/synthetic/planner_complete_output.json").read_text()
    )
    result = RunResult(
        run_id="planner-display",
        mode="replay",
        status="completed",
        duration_ms=0,
        screening=snapshot.screening,
        investigation=snapshot.investigation,
        evidence_reports=snapshot.evidence_reports,
        planner_input=snapshot,
        planner_report=plan,
    )
    validate_run(result)
    app = AppTest.from_file(str(root / "app/ui/dashboard.py"), default_timeout=10)
    app.session_state["result"] = result.model_dump(mode="json")
    app.session_state["saved_review"] = True
    app.run()
    assert not app.exception
    assert any("Next investigations" in section.value for section in app.subheader)
    assert any(plan.recommendations[0].action in block.label for block in app.expander)
    assert any(metric.label == "Follow-up actions" for metric in app.metric)
