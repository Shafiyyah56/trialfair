"""Render the actual Streamlit UI with a labelled synthetic saved-run example."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


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
    assert any("synthetic-trial-1" in item.value for item in app.markdown)
