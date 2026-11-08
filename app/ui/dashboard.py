"""Streamlit client for evidence-backed investigations and labelled saved-run review.

The backend owns credentials, model/tool execution and persistence. Uploaded
screening JSON is schema checked; saved results are validated before display.
"""

import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

# Streamlit's console entry point places this file's directory on sys.path.
# Resolve the package from the checkout even without an editable installation.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.contracts import RunResult, ScreeningOutput  # noqa: E402
from app.progress import RunAccepted, RunProgress  # noqa: E402
from app.validation import validate_run, validate_screening  # noqa: E402


def render_result(st, result: RunResult, *, saved: bool = False) -> None:
    """Show observed results and provenance without implying clinical decisions."""
    validate_run(result)
    label = "Saved result review" if saved else "Execution result"
    st.caption(f"{label} · mode: {result.mode} · model: {result.model_id or 'none recorded'}")
    st.write(f"Status: **{result.status}** · duration: {result.duration_ms / 1000:.2f}s")
    columns = st.columns(4)
    columns[0].metric(
        "Screening findings", len(result.screening.findings) if result.screening else 0
    )
    columns[1].metric("Evidence items", sum(len(r.evidence_items) for r in result.evidence_reports))
    columns[2].metric(
        "Cited sources",
        len({e.source_id for r in result.evidence_reports for e in r.evidence_items}),
    )
    columns[3].metric(
        "Follow-up actions",
        len(result.planner_report.recommendations) if result.planner_report else 0,
    )
    for error in result.errors:
        st.warning(error)
    screening = result.screening
    if not screening:
        st.info("No validated screening results are available for this run.")
        return
    bundle = screening.trial_bundle
    if bundle.is_synthetic or any(
        source.is_synthetic for report in result.evidence_reports for source in report.sources
    ):
        st.warning("Contains simulated data. This is not an observed clinical safety finding.")
    st.subheader(bundle.title)
    st.write(f"Trial: {bundle.trial_id} · Phase: {bundle.phase or 'not reported'}")
    st.write("Data availability")
    st.json(bundle.availability.model_dump(exclude={"schema_version"}))
    if bundle.demographic_rows:
        st.write("Representation as reported")
        st.dataframe([x.model_dump(exclude={"schema_version"}) for x in bundle.demographic_rows])
    st.subheader("Screening findings")
    for finding in screening.findings:
        with st.expander(f"{finding.priority.upper()} · {finding.title}", expanded=True):
            st.write(finding.description)
            st.write(
                f"Type: {finding.finding_type} · Priority rationale: {finding.priority_rationale}"
            )
            st.caption(f"Analysis IDs: {', '.join(finding.analysis_ids) or 'none'}")
            for limitation in finding.limitations:
                st.caption(limitation)
    if screening.analyses:
        with st.expander("Reproducible analyses, denominators and assumptions"):
            for analysis in screening.analyses:
                st.json(analysis.model_dump(mode="json"))
    st.subheader("Investigator assessment")
    if result.investigation:
        for assessment in result.investigation.assessed_findings:
            st.write(assessment.conclusion)
            st.caption(assessment.rationale)
            for limitation in assessment.limitations:
                st.caption(limitation)
        for hypothesis in result.investigation.hypotheses:
            st.write(f"Hypothesis ({hypothesis.status}): {hypothesis.statement}")
            contrary = ", ".join(hypothesis.contradicting_evidence_ids) or "none retrieved"
            st.caption(f"Contradictory evidence: {contrary}")
        for question in result.investigation.unresolved_questions:
            st.write(f"Follow-up question: {question}")
        for limitation in result.investigation.limitations:
            st.caption(limitation)
    st.subheader("External evidence")
    for report in result.evidence_reports:
        st.caption(f"Request {report.request_id}: {report.status}")
        for item in report.evidence_items:
            st.write(f"**{item.relation}** · {item.claim}")
            if item.source_locator.excerpt:
                with st.expander("Inspect supporting source excerpt"):
                    st.write(item.source_locator.excerpt)
            st.caption(f"Source {item.source_id} · {item.source_locator.location}")
            st.caption(item.relevance)
            for limitation in item.limitations:
                st.caption(limitation)
        for limitation in report.limitations:
            st.caption(limitation)
    st.subheader("Next investigations for human review")
    if result.planner_report:
        plan = result.planner_report
        st.caption(f"Planner status: {plan.status} · human approval required")
        for recommendation in plan.recommendations:
            with st.expander(
                f"{recommendation.priority.upper()} · {recommendation.action}", expanded=True
            ):
                st.write(recommendation.rationale)
                st.caption(recommendation.priority_rationale)
                st.write(f"Resolves: {recommendation.resolves_question}")
                st.write(f"Data: {recommendation.availability} · {recommendation.feasibility}")
                if recommendation.required_data:
                    st.write("Required data: " + "; ".join(recommendation.required_data))
                if recommendation.prerequisites:
                    st.write("Prerequisites: " + "; ".join(recommendation.prerequisites))
                st.caption("Linked findings: " + ", ".join(recommendation.finding_ids))
                st.caption(
                    "Evidence: " + (", ".join(recommendation.evidence_ids) or "evidence gap")
                )
                for limitation in recommendation.limitations:
                    st.caption(limitation)
        for limitation in plan.limitations:
            st.warning(limitation)
        with st.expander("Planning input limitations and unresolved questions"):
            for line in [*plan.input_limitations, *plan.unresolved_questions]:
                st.write(line)
    else:
        st.info("No planning output is available in this saved run.")
    st.subheader("Traceable sources")
    sources = {x.source_id: x for x in bundle.sources}
    for report in result.evidence_reports:
        sources.update({x.source_id: x for x in report.sources})
    for source in sources.values():
        st.write(source.title)
        if source.url:
            st.link_button("Open source", str(source.url))
        st.caption(f"{source.source_id} · {source.access_level} · licence: {source.licence_status}")
    if result.events:
        st.subheader("Recorded agent activity")
        st.dataframe(
            [
                {
                    "time": str(x.timestamp),
                    "agent": x.agent,
                    "action": x.event_type,
                    "summary": x.summary,
                }
                for x in result.events
            ]
        )
    for limitation in bundle.limitations:
        st.caption(limitation)
    st.caption("Research support for human review. No proposed action is executed automatically.")
    st.download_button(
        "Download validated run JSON",
        result.model_dump_json(indent=2),
        file_name="trialfair-run.json",
        mime="application/json",
    )


def render_live_progress(st, progress: RunProgress) -> None:
    """Render only actual emitted activity and completed stage outputs."""
    st.subheader("Investigation pipeline")
    st.progress(progress.progress, text=progress.stage)
    if progress.active_agent:
        st.caption(f"Active agent: **{progress.active_agent.title()}**")
        latest = progress.events[-1].summary if progress.events else "Starting this stage"
        st.caption(latest)

    stage_nodes = {
        "interpreter": ("1 Data screening", progress.screening is not None),
        "safety": ("2 Safety investigation", progress.investigation is not None),
        "evidence": ("3 Evidence review", bool(progress.evidence_reports)),
        "planner": ("4 Follow up planning", progress.planner_report is not None),
    }
    dot = [
        'digraph { rankdir=LR; bgcolor="transparent"; '
        'node [shape=box style="rounded,filled" fontname="Arial" color="#cbd5e1"];'
    ]
    for name, (label, available) in stage_nodes.items():
        color = (
            "#dbeafe" if progress.active_agent == name else "#dcfce7" if available else "#f1f5f9"
        )
        dot.append(f'{name} [label="{label}" fillcolor="{color}"];')
    dot.append(
        "interpreter -> safety; safety -> evidence; evidence -> safety; safety -> planner; }"
    )
    st.graphviz_chart("\n".join(dot), use_container_width=True)
    st.caption("Blue: active agent · Green: output available · Grey: pending")
    stages = [
        ("Trial data screening", progress.screening is not None),
        ("Safety investigation", progress.investigation is not None),
        ("External evidence", bool(progress.evidence_reports)),
        ("Follow-up planning", progress.planner_report is not None),
    ]
    columns = st.columns(4)
    for column, (label, complete) in zip(columns, stages, strict=True):
        column.metric(label, "Available" if complete else "Pending")

    if progress.screening:
        with st.expander("Screening output", expanded=True):
            st.write(progress.screening.trial_bundle.title)
            for finding in progress.screening.findings:
                st.write(f"**{finding.priority.upper()} · {finding.title}**")
                st.caption(finding.description)

    if progress.evidence_reports:
        with st.expander("Evidence output", expanded=True):
            for report in progress.evidence_reports:
                st.write(f"Request {report.request_id}: **{report.status}**")
                for item in report.evidence_items:
                    st.write(f"{item.relation.title()}: {item.claim}")
                    st.caption(f"Source {item.source_id} · {item.source_locator.location}")

    if progress.events:
        st.write("Live activity")
        labels = {
            "interpreter": "Trial data interpretation",
            "safety": "Safety investigation",
            "evidence": "External evidence research",
            "orchestrator": "Result validation",
        }
        st.dataframe(
            [
                {
                    "stage": labels[event.agent],
                    "activity": event.summary,
                }
                for event in progress.events[-8:]
            ],
            hide_index=True,
            use_container_width=True,
        )
    if progress.error:
        st.warning(progress.error)


def run_with_live_updates(st, backend: str, path: str, payload: dict) -> RunResult:
    """Start a background run and poll its real sanitized progress snapshots."""
    response = httpx.post(backend + path + "/async", json=payload, timeout=10)
    response.raise_for_status()
    accepted = RunAccepted.model_validate(response.json())
    panel = st.empty()
    deadline = time.monotonic() + 930
    while time.monotonic() < deadline:
        response = httpx.get(backend + accepted.progress_url, timeout=10)
        response.raise_for_status()
        progress = RunProgress.model_validate(response.json())
        with panel.container():
            render_live_progress(st, progress)
        if progress.result_available:
            result_response = httpx.get(f"{backend}/runs/{accepted.run_id}", timeout=10)
            result_response.raise_for_status()
            return RunResult.model_validate(result_response.json())
        if progress.status == "failed":
            raise ValueError(progress.error or "Investigation stopped before producing a result")
        time.sleep(0.75)
    raise httpx.TimeoutException("Investigation progress polling exceeded the local time limit")


def main() -> None:
    """Execute through the API or review a saved result; never silently replay live input."""
    import streamlit as st

    st.set_page_config(page_title="TrialFair", layout="wide")
    st.title("TrialFair")
    st.write("Investigate sex-specific clinical trial safety signals and missing evidence.")
    st.caption("Trial screening, safety investigation and external evidence for human review.")
    backend = "http://127.0.0.1:8000"
    action = st.radio(
        "Input", ["Curated demo", "Completed trial", "Prepared screening JSON", "Review saved run"]
    )
    with st.form("investigation"):
        upload = None
        nct_id = ""
        narrative = ""
        run_id = ""
        if action == "Curated demo":
            nct_id = "NCT04280705"
            st.info(
                "ACTT-1 remdesivir demonstration: real captured trial data, three "
                "preselected publications and prepared evidence annotations. Other model "
                "stages run live when available. This is not an autonomous literature search."
            )
        elif action == "Completed trial":
            nct_id = st.text_input("ClinicalTrials.gov NCT identifier")
            narrative = st.text_area("Optional trial symptom descriptions", max_chars=20000)
            st.caption(
                "Retrieves registry results, screens available data and investigates findings."
            )
        elif action == "Review saved run":
            run_id = st.text_input("Previously stored run ID (optional)")
            upload = st.file_uploader("Or select saved RunResult JSON", type=["json"])
        else:
            upload = st.file_uploader("Agent 1 ScreeningOutput JSON", type=["json"])
            st.caption("Execution uses the configured live model. Simulated inputs stay labelled.")
        submitted = st.form_submit_button(
            "Review" if action == "Review saved run" else "Investigate"
        )
    if submitted:
        try:
            if upload is not None and upload.size > 2_000_000:
                raise ValueError("JSON upload exceeds 2 MB limit")
            with st.spinner(
                "Reviewing result..."
                if action == "Review saved run"
                else "Investigation running..."
            ):
                if action == "Review saved run":
                    if upload:
                        result = RunResult.model_validate_json(upload.getvalue())
                    elif run_id.strip():
                        response = httpx.get(f"{backend}/runs/{run_id.strip()}", timeout=10)
                        response.raise_for_status()
                        result = RunResult.model_validate(response.json())
                    else:
                        raise ValueError("Select a saved result or enter a run ID")
                else:
                    if action == "Prepared screening JSON":
                        if upload is None:
                            raise ValueError("Select a ScreeningOutput JSON file")
                        screening = ScreeningOutput.model_validate_json(upload.getvalue())
                        validate_screening(screening)
                        path = "/investigations"
                        payload = {"screening": screening.model_dump(mode="json"), "mode": "live"}
                    else:
                        path = "/demo/runs" if action == "Curated demo" else "/runs"
                        payload = {"nct_id": nct_id.strip(), "mode": "live"}
                        if narrative.strip():
                            digest = hashlib.sha256(narrative.encode()).hexdigest()
                            payload["narrative_entries"] = [
                                {
                                    "entry_id": f"narrative-{digest[:16]}",
                                    "text": narrative,
                                    "locator": {
                                        "source_id": f"upload-{digest}",
                                        "location": "dashboard.symptom_descriptions",
                                    },
                                }
                            ]
                    result = run_with_live_updates(st, backend, path, payload)
                validate_run(result)
                st.session_state["result"] = result.model_dump(mode="json")
                st.session_state["saved_review"] = action == "Review saved run"
        except httpx.HTTPStatusError as exc:
            detail = exc.response.json().get("detail", "Backend rejected the request")
            st.error(str(detail))
        except (ValueError, json.JSONDecodeError):
            st.error("Invalid input or result. Check the shared schema and source references.")
        except httpx.RequestError:
            st.error("Backend unavailable or request timed out. Start the local FastAPI server.")
    if "result" in st.session_state:
        render_result(
            st,
            RunResult.model_validate(st.session_state["result"]),
            saved=st.session_state.get("saved_review", False),
        )


if __name__ == "__main__":
    main()
