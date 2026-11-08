"""Streamlit client for evidence-backed investigations and labelled saved-run review.

The backend owns credentials, model/tool execution and persistence. Uploaded
screening JSON is schema checked; saved results are validated before display.
"""

import base64
import hashlib
import json
import re
import sys
import time
from html import escape
from pathlib import Path

import httpx

# Streamlit's console entry point places this file's directory on sys.path.
# Resolve the package from the checkout even without an editable installation.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.contracts import RunResult, ScreeningOutput  # noqa: E402
from app.progress import RunAccepted, RunProgress  # noqa: E402
from app.synthetic_upload import (  # noqa: E402
    CSV_NAMES,
    MAX_UPLOAD_BYTES,
    PROFILE_LABELS,
    SyntheticUpload,
    sample_bundle,
)
from app.ui.reporting import (  # noqa: E402
    report_flags,
    report_html,
    report_markdown,
    report_summary,
    shared_action_limits,
    source_records,
    unique,
)
from app.validation import validate_run, validate_screening  # noqa: E402


class UploadValidationError(ValueError):
    """Only application-authored, display-safe messages."""


def apply_theme(st):
    st.markdown(
        """<style>
    .stApp{background:#f6f8fc;color:#182d42}
    .block-container{max-width:1240px;padding-top:2rem;padding-bottom:4rem}
    h1,h2,h3,h4{color:#172c42;letter-spacing:-.025em}
    h1{font-size:2.6rem!important;font-weight:750!important}
    h2{font-size:1.55rem!important}h3{font-size:1.25rem!important}
    [data-testid="stSidebar"]{background:#172c42}
    [data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] p,[data-testid="stSidebar"] label,
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:#e3edf6}
    [data-testid="stMetric"]{background:white;border:1px solid #e2e9f1;
    border-radius:12px;padding:16px 18px;min-height:96px}
    [data-testid="stMetricLabel"]{color:#64748b;font-size:.82rem}
    [data-testid="stMetricValue"]{font-size:1.65rem;color:#172c42}
    [data-testid="stForm"]{background:white;border:1px solid #e2e9f1;border-radius:14px}
    [data-testid="stExpander"]{background:white;border-color:#e2e9f1;border-radius:10px}
    [data-baseweb="tab-list"]{background:#eaf0f6;border-radius:10px;padding:5px;gap:4px}
    [data-baseweb="tab"]{padding:10px 18px;border-radius:7px}
    [aria-selected="true"][data-baseweb="tab"]{background:white;color:#246d75}
    [data-testid="stBaseButton-primary"]{background:#246d75;border-color:#246d75}
    .tf-eyebrow{font-size:.72rem;font-weight:700;letter-spacing:.15em;
    color:#60758a;margin:12px 0 8px}
    .tf-pill{display:inline-block;font-size:.76rem;font-weight:600;padding:7px 12px;
    border-radius:20px;margin:4px 0 14px;background:#e9eef5;color:#37516a}
    .tf-amber{background:#fff0d3;color:#795313}.tf-teal{background:#e0f1ed;color:#21625a}
    .stAlert{border-radius:10px}
    </style>""",
        unsafe_allow_html=True,
    )


def csv_upload_payload(files, profile, confirmed):
    if not confirmed:
        raise UploadValidationError("Confirm these are simulated records before continuing.")
    prepared = []
    seen = set()
    for file in files:
        name = file.name.lower()
        if name not in CSV_NAMES:
            raise UploadValidationError(
                "Upload only dm.csv, ae.csv, pp.csv, eg.csv or narratives.csv."
            )
        if name in seen:
            raise UploadValidationError("Upload each CSV domain only once.")
        seen.add(name)
        raw = file.getvalue()
        if len(raw) > MAX_UPLOAD_BYTES:
            raise UploadValidationError("Each CSV must be at most 2 MB.")
        prepared.append({"name": name, "data_base64": base64.b64encode(raw).decode()})
    if not {"dm.csv", "ae.csv"} <= seen:
        raise UploadValidationError("Select both dm.csv and ae.csv. Other CSVs are optional.")
    return SyntheticUpload(profile=profile, is_synthetic=True, files=prepared).model_dump(
        mode="json"
    )


def render_upload_preview(st, preview):
    st.success(f"Files validated · {preview['trial_id']}")
    columns = st.columns(3)
    columns[0].metric("Safety population", preview["safety_population"])
    columns[1].metric("PK measurements", "Available" if preview["pk_available"] else "Not supplied")
    columns[2].metric("ECG / QTc", "Available" if preview["ecg_available"] else "Not supplied")
    st.caption(
        "Reported categories: "
        + " · ".join(f"{key}: {value}" for key, value in preview["reported_sex_counts"].items())
    )
    st.caption(preview["note"])
    with st.expander("File checks and data coverage"):
        st.write("Files: " + ", ".join(preview["files"]))
        st.write("Study arms: " + "; ".join(preview["arms"]))
        for line in preview["limitations"]:
            st.caption(line)


def _pill(st, text, kind="neutral"):
    st.markdown(f'<span class="tf-pill tf-{kind}">{escape(text)}</span>', unsafe_allow_html=True)


def _render_final_report(st, result):
    bundle = result.screening.trial_bundle
    plan = result.planner_report
    flags = report_flags(result)
    st.markdown('<div class="tf-eyebrow">TRIAL IMPROVEMENT REPORT</div>', unsafe_allow_html=True)
    st.subheader("Next investigations for human review")
    st.write(report_summary(result))
    status_columns = st.columns(3)
    status_columns[0].caption(f"Study: {bundle.trial_id}")
    status_columns[1].caption(f"Plan status: {plan.status if plan else 'unavailable'}")
    status_columns[2].caption("Human review required")
    if not plan or not plan.recommendations:
        st.info(
            "No selected follow-up actions are available. Review the outstanding findings below."
        )
    else:
        st.markdown("#### Prioritised action plan")
        st.dataframe(
            [
                {
                    "Order": f"{i:02d}",
                    "Priority": rec.priority.title(),
                    "Proposed action": rec.action,
                    "Data": rec.availability.replace("_", " ").title(),
                }
                for i, rec in enumerate(plan.recommendations, 1)
            ],
            hide_index=True,
            use_container_width=True,
        )
        common = shared_action_limits(plan)
        finding_names = {f.finding_id: f.title for f in result.screening.findings}
        for number, rec in enumerate(plan.recommendations, 1):
            with st.expander(
                f"{number:02d} · {rec.priority.upper()} · {rec.action}", expanded=number == 1
            ):
                st.markdown("**Why this action**")
                st.write(rec.rationale)
                st.caption(rec.priority_rationale)
                left, right = st.columns(2)
                with left:
                    st.markdown("**Question to resolve**")
                    st.write(rec.resolves_question)
                    st.markdown("**Required data**")
                    for item in rec.required_data:
                        st.write("• " + item)
                with right:
                    st.markdown("**Feasibility and prerequisites**")
                    st.write(rec.feasibility)
                    for item in rec.prerequisites:
                        st.write("• " + item)
                st.markdown("**Connected findings**")
                for fid in rec.finding_ids:
                    st.write(finding_names.get(fid, fid))
                for line in rec.limitations:
                    if line not in common:
                        st.caption(line)
                with st.expander("Traceability references"):
                    st.caption("Finding IDs: " + ", ".join(rec.finding_ids))
                    st.caption("Analysis IDs: " + (", ".join(rec.analysis_ids) or "none"))
                    st.caption("Evidence IDs: " + (", ".join(rec.evidence_ids) or "none linked"))
                    st.caption("Source IDs: " + (", ".join(rec.source_ids) or "none linked"))
        st.markdown("#### Conditions before acting")
        st.write(
            "A researcher must check source applicability, denominators and uncertainty, "
            "then approve any further investigation. No proposed action is executed automatically."
        )
        if flags["synthetic"]:
            st.caption("This report describes simulated participants and a fictional compound.")
        with st.expander("Uncertainty, limitations and unresolved questions"):
            for line in unique([*plan.limitations, *plan.input_limitations, *common]):
                st.write("• " + line)
            if plan.unresolved_questions:
                st.markdown("**Questions that remain open**")
                for question in unique(plan.unresolved_questions):
                    st.write("• " + question)
    st.markdown("#### Export this review")
    filename = "trialfair-" + re.sub(r"[^A-Za-z0-9_-]+", "-", bundle.trial_id).strip("-")
    columns = st.columns(3)
    columns[0].download_button(
        "Download report",
        report_html(result),
        file_name=f"{filename}-report.html",
        mime="text/html",
        type="primary",
    )
    columns[1].download_button(
        "Editable report (.md)",
        report_markdown(result),
        file_name=f"{filename}-report.md",
        mime="text/markdown",
    )
    columns[2].download_button(
        "Validated data (.json)",
        result.model_dump_json(indent=2),
        file_name="trialfair-run.json",
        mime="application/json",
    )
    st.caption("The HTML report opens in a browser and can be printed or saved as a PDF.")


def _render_findings(st, result):
    bundle = result.screening.trial_bundle
    st.subheader("Screening and data coverage")
    availability = bundle.availability
    columns = st.columns(4)
    for col, label, value in zip(
        columns,
        ["Representation", "Sex-stratified events", "Sex-stratified PK", "Participant data"],
        [
            availability.representation,
            availability.sex_stratified_ae,
            availability.sex_stratified_pk,
            availability.participant_level,
        ],
        strict=True,
    ):
        col.metric(label, value.replace("_", " ").title())
    for note in availability.notes:
        st.caption(note)
    st.markdown("#### Findings to investigate")
    for i, finding in enumerate(result.screening.findings, 1):
        with st.expander(f"F{i} · {finding.priority.upper()} · {finding.title}", expanded=i == 1):
            st.write(finding.description)
            st.caption(
                f"{finding.finding_type.replace('_', ' ').title()} · {finding.priority_rationale}"
            )
            for line in finding.limitations:
                st.caption(line)
    if result.investigation:
        with st.expander("Safety investigator assessment"):
            for assessment in result.investigation.assessed_findings:
                st.write(assessment.conclusion)
                st.caption(assessment.rationale)
                for line in assessment.limitations:
                    st.caption(line)
            for hypothesis in result.investigation.hypotheses:
                st.write(f"Hypothesis ({hypothesis.status}): {hypothesis.statement}")
                st.caption(
                    "Contradictory evidence: "
                    + (", ".join(hypothesis.contradicting_evidence_ids) or "none retrieved")
                )
            for line in unique(result.investigation.limitations):
                st.caption(line)
    if bundle.demographic_rows:
        with st.expander("Participant representation as reported"):
            st.caption(
                "Groups are shown separately. Totals may overlap treatment arms; do not pool them."
            )
            st.dataframe(
                [
                    {
                        "Group": r.group_id,
                        "Category": r.reported_label,
                        "Count": r.count,
                        "Denominator": r.denominator,
                        "Population": r.analysis_population,
                    }
                    for r in bundle.demographic_rows
                ],
                hide_index=True,
                use_container_width=True,
            )
    with st.expander("Reproducible analyses, denominators and assumptions"):
        for analysis in result.screening.analyses:
            st.markdown(f"**{analysis.method}** · {analysis.status}")
            st.json(analysis.model_dump(mode="json"))
    with st.expander("Data processing and interpretation limitations"):
        for line in unique(bundle.limitations):
            st.write("• " + line)


def _render_evidence(st, result):
    st.subheader("Evidence and source material")
    sources = source_records(result)
    counter = 0
    for report in result.evidence_reports:
        st.caption(f"Evidence review: {report.status}")
        for item in report.evidence_items:
            counter += 1
            source = sources[item.source_id]
            with st.container(border=True):
                st.markdown(f"**E{counter} · {item.relation.title()}**")
                st.write(item.claim)
                if source.url:
                    st.markdown(f"[{source.title}]({source.url})")
                else:
                    st.write(source.title)
                st.caption(item.relevance)
                if item.source_locator.excerpt:
                    st.markdown("**Inspected excerpt**")
                    st.info(item.source_locator.excerpt)
                with st.expander("Scope, licence and traceability"):
                    st.caption(
                        f"Access: {source.access_level} · Licence: "
                        f"{source.licence_name or source.licence_status}"
                    )
                    st.caption(f"Retrieved: {source.retrieved_at.isoformat()}")
                    st.caption(f"{item.source_id} · {item.source_locator.location}")
                    for line in item.limitations:
                        st.caption(line)
        with st.expander("Evidence review limitations"):
            for line in unique(report.limitations):
                st.write("• " + line)
    if not counter:
        st.info("No accepted external evidence items are available for this run.")
    with st.expander("All source records, including supplied data"):
        for source in sources.values():
            st.write(source.title)
            if source.url:
                st.markdown(f"[Open source]({source.url})")
            st.caption(
                f"{source.source_id} · {source.access_level} · licence: {source.licence_status}"
            )


def render_result(st, result: RunResult, *, saved: bool = False) -> None:
    """Present the existing validated report without modifying its scientific contents."""
    validate_run(result)
    st.divider()
    st.markdown('<div class="tf-eyebrow">03 · REVIEW AND EXPORT</div>', unsafe_allow_html=True)
    label = "Saved result review" if saved else "Execution result"
    st.caption(f"{label} · mode: {result.mode} · model: {result.model_id or 'none recorded'}")
    if not result.screening:
        st.info("No validated screening results are available for this run.")
        for line in result.errors:
            st.warning(line)
        return
    bundle = result.screening.trial_bundle
    st.subheader(bundle.title)
    st.caption(
        f"{bundle.trial_id} · Run status: {result.status} · "
        f"Phase: {bundle.phase or 'not reported'} · "
        f"{result.duration_ms / 1000:.1f} seconds"
    )
    flags = report_flags(result)
    tags = ["Researcher review required"]
    if flags["synthetic"]:
        tags.append("Simulated data")
    if flags["curated"]:
        tags.append("Curated literature")
    _pill(st, " · ".join(tags), "amber" if result.status != "completed" else "teal")
    if flags["synthetic"]:
        st.warning(
            "Contains simulated data. Findings describe a fictional trial, "
            "not observed clinical outcomes."
        )
    if flags["fallback"]:
        st.warning(
            "A model stage used an explicitly labelled rules-based fallback. "
            "Its assessment or draft requires researcher review."
        )
    for line in unique(result.errors):
        st.warning(line)
    columns = st.columns(4)
    columns[0].metric("Screening findings", len(result.screening.findings))
    columns[1].metric("Evidence items", sum(len(r.evidence_items) for r in result.evidence_reports))
    columns[2].metric(
        "Cited sources",
        len({e.source_id for r in result.evidence_reports for e in r.evidence_items}),
    )
    columns[3].metric(
        "Follow-up actions",
        len(result.planner_report.recommendations) if result.planner_report else 0,
    )
    report_tab, findings_tab, evidence_tab, activity_tab = st.tabs(
        ["Final report", "Findings & analyses", "Evidence & sources", "Run activity"]
    )
    with report_tab:
        _render_final_report(st, result)
    with findings_tab:
        _render_findings(st, result)
    with evidence_tab:
        _render_evidence(st, result)
    with activity_tab:
        st.subheader("Recorded agent activity")
        st.caption(
            "Observed actions from this run. This timeline does not expose private reasoning."
        )
        if result.events:
            st.dataframe(
                [
                    {
                        "Time": str(e.timestamp),
                        "Agent": e.agent.title(),
                        "Action": e.event_type,
                        "Activity": e.summary,
                    }
                    for e in result.events
                ],
                hide_index=True,
                use_container_width=True,
            )
        st.caption(f"Run ID: {result.run_id}")
    st.caption("Research support for human review. No proposed action is executed automatically.")


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
            "planner": "Follow-up planning",
            "orchestrator": "Result validation",
        }
        st.dataframe(
            [
                {
                    "stage": labels.get(event.agent, event.agent.title()),
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
            panel.empty()
            return RunResult.model_validate(result_response.json())
        if progress.status == "failed":
            raise ValueError(progress.error or "Investigation stopped before producing a result")
        time.sleep(0.75)
    raise httpx.TimeoutException("Investigation progress polling exceeded the local time limit")


def main() -> None:
    """Execute through the API or review a saved result; never silently replay live input."""
    import streamlit as st

    st.set_page_config(page_title="TrialFair", layout="wide")
    apply_theme(st)
    with st.sidebar:
        st.markdown("## TrialFair")
        st.caption("CLINICAL SAFETY WORKSPACE")
        st.divider()
        st.markdown(
            "**Your workflow**\n\n1. Add trial data\n2. Follow the investigation\n"
            "3. Review and export"
        )
        st.divider()
        advanced_inputs = st.checkbox("Additional demo and developer inputs", value=False)
        st.caption("Research support for human review. Proposed actions require approval.")
        previous = st.session_state.get("result")
        if isinstance(previous, dict) and previous.get("run_id"):
            st.caption("CURRENT REPORT")
            st.code(previous["run_id"], language=None)
    st.markdown(
        '<div class="tf-eyebrow">CLINICAL TRIAL SAFETY REVIEW</div>', unsafe_allow_html=True
    )
    st.title("TrialFair")
    st.write("Review trial data, examine the evidence and prepare follow-up investigations.")
    st.markdown('<div class="tf-eyebrow">01 · ADD YOUR TRIAL</div>', unsafe_allow_html=True)
    backend = "http://127.0.0.1:8000"
    input_options = ["Synthetic CSV upload", "Completed trial", "Review saved run"]
    if advanced_inputs:
        input_options += ["Curated demo", "Prepared screening JSON"]
    action = st.radio(
        "Input",
        input_options,
        horizontal=True,
    )
    if st.session_state.get("last_input_action", action) != action:
        st.session_state.pop("result", None)
        st.session_state.pop("upload_preview", None)
    st.session_state["last_input_action"] = action
    source_profile = "syn401"
    if action == "Synthetic CSV upload":
        st.subheader("Upload participant data")
        st.caption(
            "Demo upload accepts simulated CSV records. "
            "Use a trial identifier for public trial results."
        )
        profile_column, sample_column = st.columns([2, 1])
        source_profile = profile_column.selectbox(
            "Real class-context source profile",
            list(PROFILE_LABELS),
            format_func=PROFILE_LABELS.get,
        )
        if st.session_state.get("last_source_profile", source_profile) != source_profile:
            st.session_state.pop("result", None)
            st.session_state.pop("upload_preview", None)
        st.session_state["last_source_profile"] = source_profile
        sample_column.download_button(
            "Download sample CSV bundle",
            sample_bundle(source_profile),
            file_name=f"{source_profile}-csv.zip",
            mime="application/zip",
            use_container_width=True,
        )
        st.caption(
            "Unzip the sample, then select its CSV files below. Answer keys and generating "
            "parameters are excluded. Sources are preselected real class context, not studies "
            "of the fictional compound."
        )
        with st.expander("Preselected sources for this class profile"):
            sources = json.loads(
                (Path(_PROJECT_ROOT) / "fixtures/curated" / f"{source_profile}.json").read_text()
            )
            for item in sources["items"]:
                source = item["source"]
                st.markdown(f"[{source['title']}]({source['url']})")
                st.caption(f"Abstract excerpt · licence status: {source['licence_status']}")
    validate_upload = False
    with st.form("investigation"):
        upload = None
        nct_id = ""
        narrative = ""
        run_id = ""
        csv_files = []
        confirmed_synthetic = False
        if action == "Synthetic CSV upload":
            st.markdown("**Required:** dm.csv (participants) and ae.csv (adverse events).")
            st.caption(
                "Optional: pp.csv for PK, eg.csv for ECG/QTc, narratives.csv for written symptoms."
            )
            csv_files = st.file_uploader(
                "Select the study CSV files",
                type=["csv"],
                accept_multiple_files=True,
                max_upload_size=2,
            )
            confirmed_synthetic = st.checkbox(
                "These are simulated records, with no real patient data"
            )
            st.caption("CSV files only, at most 2 MB each. Statistics use the uploaded values.")
            validate_upload = st.form_submit_button("Validate files without running AI")
        elif action == "Curated demo":
            nct_id = "NCT04280705"
            st.info(
                "ACTT-1 remdesivir demonstration: real captured trial data, three "
                "preselected publications and prepared evidence annotations. Other model "
                "stages run live when available. This is not an autonomous literature search."
            )
        elif action == "Completed trial":
            st.subheader("Retrieve a public trial")
            nct_id = st.text_input(
                "ClinicalTrials.gov NCT identifier", placeholder="e.g. NCT04280705"
            )
            with st.expander("Add optional symptom descriptions"):
                narrative = st.text_area("Optional trial symptom descriptions", max_chars=20000)
            st.caption(
                "Retrieves registry results, screens available data and investigates findings."
            )
        elif action == "Review saved run":
            st.subheader("Reopen an existing report")
            run_id = st.text_input("Previously stored run ID (optional)")
            upload = st.file_uploader("Or select saved RunResult JSON", type=["json"])
        else:
            upload = st.file_uploader("Agent 1 ScreeningOutput JSON", type=["json"])
            st.caption("Execution uses the configured live model. Simulated inputs stay labelled.")
        submitted = st.form_submit_button(
            "Review" if action == "Review saved run" else "Investigate",
            type="primary",
        )
    if validate_upload:
        st.session_state.pop("upload_preview", None)
        try:
            payload = csv_upload_payload(csv_files, source_profile, confirmed_synthetic)
            response = httpx.post(backend + "/synthetic/preview", json=payload, timeout=30)
            response.raise_for_status()
            st.session_state["upload_preview"] = response.json()
        except UploadValidationError as exc:
            st.error(str(exc))
        except httpx.HTTPStatusError as exc:
            st.error(str(exc.response.json().get("detail", "CSV validation failed")))
        except httpx.RequestError:
            st.error("Start the local FastAPI backend to validate the uploaded CSVs.")
    if action == "Synthetic CSV upload" and not submitted and "upload_preview" in st.session_state:
        render_upload_preview(st, st.session_state["upload_preview"])
    if submitted:
        if action != "Review saved run":
            st.session_state.pop("result", None)
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
                    if action == "Synthetic CSV upload":
                        payload = csv_upload_payload(csv_files, source_profile, confirmed_synthetic)
                        preview = httpx.post(
                            backend + "/synthetic/preview", json=payload, timeout=30
                        )
                        preview.raise_for_status()
                        st.session_state["upload_preview"] = preview.json()
                        render_upload_preview(st, preview.json())
                        path = "/synthetic/runs"
                    elif action == "Prepared screening JSON":
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
        except UploadValidationError as exc:
            st.error(str(exc))
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
