"""Synthetic regressions for the four independently reproduced Agent 4 issues."""

from pathlib import Path

import pytest

from app.agents.planner import build_candidates, inspect, run_planner
from app.contracts import Hypothesis, PKRow, PlannerInput, PlannerReport, SourceLocator
from app.model_client import ModelResponse, ToolCall
from app.validation import (
    planner_input_limitations,
    validate_planner_input,
    validate_planner_report,
)

ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def phase1():
    return PlannerInput.model_validate_json(
        (ROOT / "phase1_agent4" / "planner_input.json").read_text()
    )


def pk_candidates(phase1, context_factory, parameter, provided):
    phase1.screening.findings = [phase1.screening.findings[-1]]
    phase1.investigation.assessed_findings = [
        a for a in phase1.investigation.assessed_findings if a.finding_id == "gap-pk"
    ]
    phase1.investigation.hypotheses = []
    phase1.investigation.evidence_ids = []
    phase1.evidence_reports = []
    phase1.screening.findings[0].endpoint = parameter
    phase1.screening.findings[0].title = f"Missing sex-specific {parameter or 'PK'} summaries"
    phase1.screening.trial_bundle.pk_rows = [
        PKRow(
            row_id=f"pk-{index}",
            parameter=param,
            value=100,
            unit="synthetic unit",
            summary_statistic="mean",
            reported_sex_category="Female",
            group_id="arm-active",
            sample_size=6,
            is_synthetic=True,
            source_locator=SourceLocator(source_id="phase1-synthetic", location="synthetic.pk"),
        )
        for index, param in enumerate(provided)
    ]
    validate_planner_input(phase1)
    ctx, _ = context_factory()
    ctx.datasets = {"synthetic-snapshot": phase1.screening.trial_bundle}
    return build_candidates(phase1, ctx)


@pytest.mark.parametrize(
    "requested,provided",
    [
        ("Cmax", ["AUC"]),
        ("AUC", ["Cmax"]),
        ("Tmax", ["Cmax"]),
        ("CL/F", ["CL"]),
        ("AUC0-t", ["AUC0-inf"]),
        ("Cmax", []),
        ("AUC and Cmax", ["AUC"]),
    ],
)
def test_pk_mismatch_or_missing_parameter_stays_a_gap(phase1, context_factory, requested, provided):
    candidates = pk_candidates(phase1, context_factory, requested, provided)
    assert all(c.availability != "available" for c in candidates)
    assert any(c.category == "additional_data_collection" for c in candidates)
    assert any(c.category == "future_trial_design" for c in candidates)


@pytest.mark.parametrize(
    "requested,provided",
    [
        ("Cmax", ["cMAX"]),
        ("AUC", ["AUC"]),
        ("Tmax", ["Tmax"]),
        ("CL/F", ["CL/F"]),
        ("AUC0-t", ["AUC0-t"]),
        ("Apparent clearance", ["Apparent clearance"]),
        ("Terminal elimination rate constant", ["Terminal elimination rate constant"]),
        ("AUC and Cmax", ["AUC", "Cmax"]),
    ],
)
def test_pk_exact_requested_parameters_are_available(phase1, context_factory, requested, provided):
    candidates = pk_candidates(phase1, context_factory, requested, provided)
    assert candidates[0].availability == "available"
    assert candidates[0].category == "additional_analysis"
    assert "ratios" in candidates[0].action
    assert any("Female" in lim for lim in candidates[0].limitations)


def test_unspecified_pk_parameter_cannot_be_satisfied_by_any_row(phase1, context_factory):
    candidates = pk_candidates(phase1, context_factory, None, ["AUC"])
    assert all(c.availability != "available" for c in candidates)
    assert candidates[0].category == "interpretation_review"


def test_known_representation_uses_counts_without_new_collection(phase1, context_factory):
    ctx, _ = context_factory()
    recs = [c for c in build_candidates(phase1, ctx) if c.finding_ids == ["gap-representation"]]
    assert recs and all(c.category != "additional_data_collection" for c in recs)
    assert recs[0].availability == "available"
    assert "Female" in recs[0].rationale and "6" in recs[0].rationale
    assert "Male" in recs[0].rationale and "30" in recs[0].rationale
    assert "precision" in recs[0].action.lower()
    assert any("adequacy" in lim for lim in recs[0].limitations)


def test_missing_representation_requests_specific_missing_data(phase1, context_factory):
    phase1.screening.trial_bundle.demographic_rows.clear()
    ctx, _ = context_factory()
    rec = next(c for c in build_candidates(phase1, ctx) if c.finding_ids == ["gap-representation"])
    assert rec.category == "additional_data_collection" and rec.availability == "missing"
    assert "participant counts" in rec.action


def test_partial_representation_retains_known_categories_and_targets_missing_fields(
    phase1, context_factory
):
    rows = phase1.screening.trial_bundle.demographic_rows
    rows[1].count = None
    rows[0].reported_label = "As reported: Female"
    ctx, _ = context_factory()
    recs = [c for c in build_candidates(phase1, ctx) if c.finding_ids == ["gap-representation"]]
    assert any(
        c.category == "interpretation_review" and "As reported: Female" in c.rationale for c in recs
    )
    missing = next(c for c in recs if c.category == "additional_data_collection")
    assert "Male" in " ".join(missing.required_data)
    assert "Female" not in " ".join(missing.required_data)


def test_cross_finding_evidence_preserves_both_local_and_shared_hypotheses(phase1, context_factory):
    phase1.investigation.hypotheses.extend(
        [
            Hypothesis(
                hypothesis_id="local-pk",
                statement="Synthetic PK question.",
                finding_ids=["gap-pk"],
                status="unresolved",
            ),
            Hypothesis(
                hypothesis_id="shared",
                statement="Synthetic joint question.",
                finding_ids=["signal-nausea", "gap-pk"],
                supporting_evidence_ids=["e-support"],
                contradicting_evidence_ids=["e-opposes"],
                status="unresolved",
            ),
        ]
    )
    ctx, _ = context_factory()
    candidates = build_candidates(phase1, ctx)
    pk = next(c for c in candidates if c.finding_ids == ["gap-pk"])
    assert {"local-pk", "shared"} <= set(pk.hypothesis_ids)
    assert {"e-support", "e-opposes"} <= set(pk.evidence_ids)
    assert any("applicability" in lim and "signal-nausea" in lim for lim in pk.limitations)
    packet = inspect("inspect_finding", "gap-pk", phase1, ctx, candidates)
    assert len(packet["evidence"]) == 2
    assert {e["evidence"]["evidence_id"] for e in packet["evidence"]} == set(pk.evidence_ids)
    report = PlannerReport(
        trial_id=phase1.screening.trial_bundle.trial_id,
        status="partial",
        recommendations=[pk],
        is_synthetic=True,
        input_limitations=planner_input_limitations(phase1),
    )
    validate_planner_report(report, phase1)
    pk.hypothesis_ids.remove("shared")
    with pytest.raises(ValueError, match="unrelated"):
        validate_planner_report(report, phase1)


def complete_pair():
    p = PlannerInput.model_validate_json((ROOT / "planner_complete_input.json").read_text())
    r = PlannerReport.model_validate_json((ROOT / "planner_complete_output.json").read_text())
    return p, r


def test_completed_report_rejects_unaddressed_assessed_finding():
    p, r = complete_pair()
    p.screening.findings.append(
        p.screening.findings[0].model_copy(update={"finding_id": "omitted"})
    )
    p.investigation.assessed_findings.append(
        p.investigation.assessed_findings[0].model_copy(update={"finding_id": "omitted"})
    )
    with pytest.raises(ValueError, match="disposition|address"):
        validate_planner_report(r, p)


@pytest.mark.parametrize("status", ["unresolved", "requires_further_investigation", "resolved"])
def test_explicit_valid_dispositions_can_complete_without_resolving_all_science(status):
    p, r = complete_pair()
    disposition = dict(
        finding_id="finding-gap-1",
        status=status,
        rationale="Human-reviewed planning disposition; no clinical conclusion.",
        recommendation_ids=[],
        analysis_ids=[],
        evidence_ids=[],
    )
    if status == "requires_further_investigation":
        disposition["recommendation_ids"] = [r.recommendations[0].recommendation_id]
    else:
        r.recommendations = []
    if status == "resolved":
        disposition["analysis_ids"] = [p.screening.analyses[0].analysis_id]
    payload = r.model_dump()
    payload["finding_dispositions"] = [disposition]
    r = PlannerReport.model_validate(payload)
    validate_planner_report(r, p)
    assert r.status == "completed"


@pytest.mark.parametrize(
    "bad", ["unknown-finding", "missing-follow-up", "unsupported-resolution", "duplicate"]
)
def test_invalid_dispositions_rejected(bad):
    p, r = complete_pair()
    d = dict(
        finding_id="finding-gap-1",
        status="requires_further_investigation",
        rationale="Synthetic review.",
        recommendation_ids=[r.recommendations[0].recommendation_id],
        analysis_ids=[],
        evidence_ids=[],
    )
    if bad == "unknown-finding":
        d["finding_id"] = "fabricated"
    if bad == "missing-follow-up":
        d["recommendation_ids"] = []
    if bad == "unsupported-resolution":
        d.update(status="resolved", recommendation_ids=[])
    payload = r.model_dump()
    payload["finding_dispositions"] = [d, d] if bad == "duplicate" else [d]
    with pytest.raises(ValueError):
        validate_planner_report(PlannerReport.model_validate(payload), p)


@pytest.mark.anyio
async def test_generated_plan_disposes_each_assessed_finding_without_claiming_resolution(
    phase1, context_factory
):
    ctx, _ = context_factory()
    ctx.datasets = {"snapshot": phase1.screening.trial_bundle}
    candidates = build_candidates(phase1, ctx)
    fids = [f.finding_id for f in phase1.screening.findings]
    ctx.model.responses = iter(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        call_id=f"inspect-{fid}",
                        name="inspect_finding",
                        arguments={"identifier": fid},
                    )
                    for fid in fids
                ]
            ),
            ModelResponse(
                structured_output={
                    "choices": [
                        dict(
                            recommendation_id=c.recommendation_id,
                            priority="medium",
                            reason="follow_up",
                        )
                        for c in candidates
                    ]
                }
            ),
        ]
    )
    report = await run_planner(phase1, ctx)
    assert report.recommendations
    assert {d.finding_id for d in report.finding_dispositions} == set(fids)
    assert all(
        d.status == "requires_further_investigation" and d.recommendation_ids
        for d in report.finding_dispositions
    )
    assert report.status == "partial"


def test_completion_rejects_disposition_with_an_unavailable_analysis():
    p, r = complete_pair()
    p.screening.analyses[0].status = "unavailable"
    # Even partial reports cannot call an unavailable analysis a resolved basis.
    r.status = "partial"
    r.input_limitations = planner_input_limitations(p)
    r.recommendations = []
    payload = r.model_dump()
    payload["finding_dispositions"] = [
        dict(
            finding_id="finding-gap-1",
            status="resolved",
            rationale="Synthetic review.",
            analysis_ids=[p.screening.analyses[0].analysis_id],
            evidence_ids=[],
            recommendation_ids=[],
        )
    ]
    with pytest.raises(ValueError, match="unavailable"):
        validate_planner_report(PlannerReport.model_validate(payload), p)


def test_relevant_hypothesis_cannot_be_silently_removed(phase1, context_factory):
    ctx, _ = context_factory()
    rec = next(c for c in build_candidates(phase1, ctx) if c.finding_ids == ["signal-nausea"])
    rec.hypothesis_ids = []
    report = PlannerReport(
        trial_id=phase1.screening.trial_bundle.trial_id,
        status="partial",
        recommendations=[rec],
        is_synthetic=True,
        input_limitations=planner_input_limitations(phase1),
    )
    with pytest.raises(ValueError, match="retain relevant hypotheses"):
        validate_planner_report(report, phase1)


def test_pk_rows_from_unrelated_sources_cannot_satisfy_parameter(phase1, context_factory):
    candidates = pk_candidates(phase1, context_factory, "Cmax", ["Cmax"])
    assert candidates[0].availability == "available"
    phase1.screening.trial_bundle.sources.append(
        phase1.screening.trial_bundle.sources[0].model_copy(
            update={"source_id": "unrelated-synthetic-source"}
        )
    )
    phase1.screening.trial_bundle.pk_rows[0].source_locator.source_id = "unrelated-synthetic-source"
    validate_planner_input(phase1)
    ctx, _ = context_factory()
    ctx.datasets = {"snapshot": phase1.screening.trial_bundle}
    assert build_candidates(phase1, ctx)[0].availability == "missing"
