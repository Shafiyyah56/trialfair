"""Explicit curated demonstration using real captured sources and the live shared model.

Only literature selection/annotations are prepared. Never substitute these for an
autonomous search or apply the remdesivir profile to another drug/trial.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.agents.evidence import EvidenceDraft, EvidenceState, compile_evidence_report
from app.contracts import (
    AgentEvent,
    EvidenceItem,
    EvidenceReport,
    EvidenceRequest,
    FindingAssessment,
    InvestigationReport,
    SourceRecord,
)

ROOT = Path(__file__).resolve().parents[1]
DEMO_TRIAL = "NCT04280705"
DEMO_LABEL = (
    "Curated demonstration: developer-selected literature and prepared excerpt annotations; "
    "not an autonomous or exhaustive search. Other model stages run live when available."
)


def build_demo_context(run_id, mode, *, registry_capture=True):
    """Explicit demo runtime: captured real inputs, curated review, live model stages."""
    from app.config import Settings
    from app.runtime import build_context

    settings = Settings()
    settings = Settings.model_validate(
        {
            **settings.model_dump(by_alias=True),
            "TRIALFAIR_RUN_TIMEOUT_SECONDS": settings.demo_timeout_seconds,
            "TRIALFAIR_MAX_MODEL_TURNS": max(18, settings.max_model_turns),
        }
    )
    context = build_context(run_id, mode, settings=settings)
    return configure_demo_context(context) if registry_capture else context


def configure_demo_context(context):
    """Reuse the actual registry capture with its original hash/date; never label it fresh."""
    context.demo_profile = "remdesivir-curated"
    context.evidence_handler = run_curated_evidence
    if context.planner_handler is None:
        from app.agents.planner import run_planner

        context.planner_handler = run_planner
    capture = ROOT / f"fixtures/public/{DEMO_TRIAL}.json"
    provenance = json.loads(capture.with_suffix(".provenance.json").read_text())
    raw = capture.read_bytes()
    context.registry.load_capture(
        raw,
        SourceRecord(
            source_id=f"ctgov-{DEMO_TRIAL}-{provenance['sha256'][:12]}",
            source_type="trial_registry",
            title="ACTT-1 captured public trial record",
            url=provenance["url"],
            external_id=DEMO_TRIAL,
            retrieved_at=provenance["retrieved_at"],
            content_hash=provenance["sha256"],
            licence_status=provenance["licence_status"],
            access_level="full_text",
            is_synthetic=False,
        ),
    )
    return context


def demo_event(context, agent, kind, summary, ids=()):
    context.emit(
        AgentEvent(
            event_id=str(uuid4()),
            run_id=context.run_id,
            timestamp=datetime.now(UTC),
            agent=agent,
            event_type=kind,
            summary=summary,
            related_ids=list(ids),
        )
    )


async def run_curated_evidence(request, context) -> EvidenceReport:
    """Inspect packaged, hash-checked excerpts and validate their prepared annotations."""
    request = EvidenceRequest.model_validate_json(request.model_dump_json())
    profile = context.demo_profile or "remdesivir-curated"
    filename = {
        "remdesivir-curated": "remdesivir.json",
        "syn401": "syn401.json",
        "syn722": "syn722.json",
        "syn318": "syn318.json",
    }.get(profile)
    if filename is None:
        raise ValueError("Unknown curated source profile")
    payload = json.loads((ROOT / "fixtures/curated" / filename).read_text())
    matches = (
        request.trial_id == payload["trial_id"]
        if "trial_id" in payload
        else request.trial_id.startswith(payload["trial_prefix"])
    )
    if not matches:
        raise ValueError("Curated profile only supports its matching trial or study prefix")
    if profile != "remdesivir-curated" and not request.trial_id.startswith("SYN-"):
        raise ValueError("Curated trial identity mismatch")
    state = EvidenceState()
    state.limitations.append(DEMO_LABEL)
    state.limitations.append(payload["selection"])
    demo_event(
        context,
        "evidence",
        "decision",
        f"Reviewing {len(payload['items'])} preselected real class-context publications.",
    )
    items = []
    for index, entry in enumerate(payload["items"]):
        source = SourceRecord.model_validate(entry["source"])
        quote = entry["quote"]
        if hashlib.sha256(quote.encode()).hexdigest() != entry["excerpt_hash"]:
            raise ValueError("Curated excerpt hash mismatch")
        demo_event(
            context,
            "evidence",
            "tool_call",
            f"Inspecting curated abstract excerpt: {source.external_id}.",
            [source.source_id],
        )
        state.register_passage(source, entry["location"], quote)
        items.append(
            EvidenceItem(
                evidence_id=f"curated-{index}",
                source_id=source.source_id,
                finding_ids=request.finding_ids,
                claim=entry["claim"],
                relation=entry["relation"],
                source_locator={
                    "source_id": source.source_id,
                    "location": entry["location"],
                    "excerpt": quote,
                },
                study_design=entry["study_design"],
                relevance=entry["relevance"],
                limitations=[
                    *entry["limitations"],
                    "Prepared annotation of a captured abstract excerpt.",
                ],
            )
        )
        demo_event(
            context,
            "evidence",
            "tool_result",
            f"Verified curated excerpt and provenance: {source.external_id}.",
            [source.source_id],
        )
    report = compile_evidence_report(
        EvidenceDraft(
            evidence_items=items,
            status="partial",
            unresolved_questions=payload.get(
                "unresolved_questions",
                [
                    "Are sex-stratified cardiac event counts and denominators available?",
                    "Do exposure and clinical risk differ by sex after accounting for confounders?",
                ],
            ),
            limitations=[DEMO_LABEL],
        ),
        request,
        context,
        state,
    )
    demo_event(
        context,
        "evidence",
        "stop",
        f"Curated review retained {len(report.evidence_items)} cited items; "
        "human sex-specific questions remain open.",
    )
    return report


async def ensure_demo_evidence(screening, context):
    """Guarantee an explicit curated review even when the safety model cannot finish."""
    if context.evidence_reports or not screening.findings:
        return
    context.budget.consume("evidence_request")
    report = await run_curated_evidence(
        EvidenceRequest(
            request_id=f"curated-{context.run_id}",
            trial_id=screening.trial_bundle.trial_id,
            finding_ids=[finding.finding_id for finding in screening.findings],
            question="Which preselected sources inform the screened safety evidence gaps?",
            drug_names=screening.trial_bundle.interventions,
        ),
        context,
    )
    context.evidence_reports.append(report)
    demo_event(
        context, "evidence", "revision", "Curated evidence output is ready for safety review."
    )


def source_review_fallback(screening, context, previous):
    """Visible rules-based review, never represented as a successful model assessment."""
    items = [item for report in context.evidence_reports for item in report.evidence_items]
    assessments = [
        FindingAssessment(
            finding_id=finding.finding_id,
            conclusion=finding.description,
            priority=finding.priority,
            rationale="Rules-based fallback retains the screening finding for human review.",
            analysis_ids=finding.analysis_ids,
            evidence_ids=[
                item.evidence_id for item in items if finding.finding_id in item.finding_ids
            ],
            limitations=[
                "Model assessment unavailable; prepared review is not a new clinical conclusion.",
                *finding.limitations,
            ],
        )
        for finding in screening.findings
    ]
    return InvestigationReport(
        trial_id=screening.trial_bundle.trial_id,
        status="partial",
        assessed_findings=assessments,
        evidence_ids=[item.evidence_id for item in items],
        completed_analysis_ids=[
            a.analysis_id for a in screening.analyses if a.status == "completed"
        ],
        unresolved_questions=[
            question for r in context.evidence_reports for question in r.unresolved_questions
        ],
        limitations=[
            *previous.limitations,
            DEMO_LABEL,
            "Rules-based assessment fallback; the live model did not complete this assessment.",
        ],
    )


async def run_demo_safety(screening, context):
    from app.agents.safety import run_safety

    demo_event(
        context,
        "safety",
        "decision",
        "Requesting curated evidence review for the screened findings.",
    )
    await ensure_demo_evidence(screening, context)
    report = await run_safety(screening, context)
    if not report.assessed_findings and screening.findings:
        demo_event(
            context,
            "safety",
            "revision",
            "Live assessment unavailable; retaining source-linked rules-based review.",
        )
        return source_review_fallback(screening, context, report)
    report.limitations.append(DEMO_LABEL)
    return report


def draft_plan_fallback(planner_input, context, previous):
    """Preserve safe candidate actions as a labelled rules draft if provider selection fails."""
    from app.agents.planner import build_candidates
    from app.validation import validate_planner_report

    candidates = build_candidates(planner_input, context)[:8]
    report = previous.model_copy(
        update={
            "status": "partial",
            "recommendations": candidates,
            "limitations": [
                *previous.limitations,
                "Rules-based draft from validated action templates; the live planner did not "
                "complete selection. A researcher must select and prioritise these actions.",
            ],
        }
    )
    validate_planner_report(report, planner_input)
    demo_event(
        context,
        "planner",
        "revision",
        "Live selection unavailable; presenting validated candidate actions as a rules draft.",
    )
    demo_event(context, "planner", "stop", "Draft follow-up plan ready for human review.")
    return report
