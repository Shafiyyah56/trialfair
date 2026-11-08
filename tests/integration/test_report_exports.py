"""Readable report exports preserve validated contents and escape untrusted text."""

from html import escape
from pathlib import Path

from app.contracts import PlannerInput, PlannerReport, RunResult
from app.ui.reporting import report_html, report_markdown

ROOT = Path(__file__).resolve().parents[2]


def complete_report():
    snapshot = PlannerInput.model_validate_json(
        (ROOT / "fixtures/synthetic/planner_complete_input.json").read_text()
    )
    plan = PlannerReport.model_validate_json(
        (ROOT / "fixtures/synthetic/planner_complete_output.json").read_text()
    )
    return RunResult(
        run_id="export-test",
        mode="replay",
        status="completed",
        duration_ms=1234,
        screening=snapshot.screening,
        investigation=snapshot.investigation,
        evidence_reports=snapshot.evidence_reports,
        planner_input=snapshot,
        planner_report=plan,
    )


def test_readable_exports_preserve_report_and_human_review():
    result = complete_report()
    original = result.model_dump_json()
    markdown, html = report_markdown(result), report_html(result)
    assert "Trial improvement report" in markdown
    assert "Human review required" in markdown
    assert "SIMULATED DATA" in html
    for rec in result.planner_report.recommendations:
        assert rec.action in markdown
        assert escape(rec.action) in html
        assert rec.resolves_question in markdown
        assert all(value in markdown for value in rec.required_data)
    assert result.model_dump_json() == original


def test_html_export_escapes_uploaded_title_and_preserves_partial_status():
    result = complete_report()
    result.screening.trial_bundle.title = '<script>alert("untrusted")</script>'
    result.planner_input.screening.trial_bundle.title = result.screening.trial_bundle.title
    result.status = "partial"
    html = report_html(result)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Run status: partial" in html
    assert "No analysis, experiment, dose change" in html
