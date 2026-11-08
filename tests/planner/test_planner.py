"""Offline behavioural checks; synthetic evidence is not clinical validation."""

import asyncio
from time import monotonic

import pytest
from pydantic import ValidationError

from app.agents.planner import build_candidates, run_planner
from app.contracts import (
    AdverseEventRow,
    EvidenceItem,
    EvidenceReport,
    Finding,
    Hypothesis,
    PlannerInput,
    PlannerReport,
    SourceLocator,
)
from app.model_client import ModelResponse, ToolCall
from app.validation import planner_input_limitations, validate_planner_report


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def snapshot(screening, investigation):
    return PlannerInput(screening=screening, investigation=investigation, evidence_reports=[])


def call(name, identifier, call_id="lookup"):
    return ToolCall(call_id=call_id, name=name, arguments={"identifier": identifier})


def responses(candidate, fid="finding-gap-1", *, priority="high", reason="data_prerequisite"):
    return [
        ModelResponse(tool_calls=[call("inspect_finding", fid)], continuation="opaque-test-token"),
        ModelResponse(
            structured_output={
                "choices": [
                    {
                        "recommendation_id": candidate.recommendation_id,
                        "priority": priority,
                        "reason": reason,
                    }
                ]
            }
        ),
    ]


def make_evidence(snapshot, relation="contradicts", eid="evidence-contrary"):
    source = snapshot.screening.trial_bundle.sources[0].model_copy(
        update={
            "source_id": "synthetic-publication",
            "access_level": "abstract",
        }
    )
    item = EvidenceItem(
        evidence_id=eid,
        source_id=source.source_id,
        finding_ids=["finding-gap-1"],
        claim="Synthetic contradiction for software tests only.",
        relation=relation,
        source_locator=SourceLocator(
            source_id=source.source_id,
            location="abstract",
            excerpt="Synthetic contradiction for software tests only.",
        ),
        relevance="Synthetic applicability is unverified.",
        limitations=["Synthetic abstract only."],
    )
    snapshot.evidence_reports = [
        EvidenceReport(
            request_id="synthetic-research",
            status="completed",
            sources=[source],
            evidence_items=[item],
        )
    ]
    return item


@pytest.mark.anyio
async def test_specific_gap_plan_preserves_shared_budget_and_history(snapshot, context_factory):
    ctx, events = context_factory()
    candidate = build_candidates(snapshot, ctx)[0]
    ctx.model.responses = iter(responses(candidate))
    ctx.budget.used["model_turn"] = 3
    original_deadline = ctx.budget.deadline
    report = await run_planner(snapshot, ctx)
    assert report.status == "partial"
    rec = report.recommendations[0]
    assert "affected-participant" in rec.action
    assert rec.category == "additional_data_collection"
    assert rec.availability == "missing"
    assert rec.analysis_ids == ["analysis-availability-1"]
    assert rec.source_ids == ["source-synthetic-1"]
    assert rec.evidence_ids == []
    assert report.human_review_required and report.is_synthetic
    assert ctx.budget.used == {"model_turn": 5}
    assert ctx.budget.deadline == original_deadline
    history = ctx.model.calls[1][0]
    assert any(
        m.role == "assistant" and m.content["continuation"] == "opaque-test-token" for m in history
    )
    assert any(m.role == "tool" for m in history)
    assert [e.event_type for e in events] == ["decision", "tool_result", "revision", "stop"]
    assert all(e.agent == "planner" and e.run_id == ctx.run_id for e in events)
    validate_planner_report(report, snapshot)


@pytest.mark.anyio
async def test_retains_contradictions_exact_support_and_access(snapshot, context_factory):
    item = make_evidence(snapshot)
    snapshot.investigation.hypotheses = [
        Hypothesis(
            hypothesis_id="hyp-1",
            statement="Synthetic hypothesis, not a fact.",
            finding_ids=["finding-gap-1"],
            contradicting_evidence_ids=[item.evidence_id],
            status="weakened",
        )
    ]
    ctx, _ = context_factory()
    c = build_candidates(snapshot, ctx)[-1]
    ctx.model.responses = iter(responses(c, reason="conflicting_evidence"))
    report = await run_planner(snapshot, ctx)
    rec = report.recommendations[0]
    assert item.evidence_id in rec.evidence_ids
    assert "hyp-1" in rec.hypothesis_ids
    assert "synthetic-publication" in rec.source_ids
    assert "Evidence is abstract-only." in rec.limitations
    tool = next(m.content["result"] for m in ctx.model.calls[-1][0] if m.role == "tool")
    assert tool["evidence"][0]["evidence"]["source_locator"] == item.source_locator.model_dump()
    assert tool["evidence"][0]["source"]["access_level"] == "abstract"
    rec.evidence_ids.clear()
    rec.source_ids.remove("synthetic-publication")
    with pytest.raises(ValueError, match="contradictory"):
        validate_planner_report(report, snapshot)


@pytest.mark.anyio
async def test_unassessed_fallback_remains_useful_partial(snapshot, context_factory):
    snapshot.investigation.assessed_findings.clear()
    snapshot.investigation.status = "unavailable"
    ctx, _ = context_factory()
    ctx.model.responses = iter(responses(build_candidates(snapshot, ctx)[0]))
    report = await run_planner(snapshot, ctx)
    assert report.status == "partial" and report.recommendations
    assert "Some screened findings have not been assessed." in report.input_limitations
    assert any("No accepted" in x for x in report.input_limitations)
    report.status = "completed"
    with pytest.raises(ValueError, match="upstream"):
        validate_planner_report(report, snapshot)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [RuntimeError("secret must not appear"), TimeoutError()])
async def test_provider_failure_is_sanitised_unavailable(snapshot, context_factory, failure):
    ctx, events = context_factory([failure])
    report = await run_planner(snapshot, ctx)
    assert report.status == "unavailable" and not report.recommendations
    assert "secret" not in report.model_dump_json()
    assert "secret" not in str(events)
    assert ctx.budget.used["model_turn"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("expired", [False, True])
async def test_exhausted_budget_makes_zero_provider_calls(snapshot, context_factory, expired):
    ctx, _ = context_factory()
    if expired:
        ctx.budget.deadline = monotonic() - 1
    else:
        ctx.budget.used["model_turn"] = ctx.budget.limits["model_turn"] - 1
    report = await run_planner(snapshot, ctx)
    assert report.status == "unavailable"
    assert not ctx.model.calls


@pytest.mark.anyio
async def test_hanging_provider_cancelled_at_original_deadline(snapshot, context_factory):
    ctx, _ = context_factory()

    cancelled = []

    async def timed(*args, **kwargs):
        # Shorten the test helper's remaining_seconds without changing production limits.
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    original_remaining = ctx.budget.remaining_seconds
    ctx.model.generate = timed
    calls = []

    def remaining():
        calls.append(True)
        return original_remaining() if len(calls) == 1 else 0.01

    ctx.budget.remaining_seconds = remaining
    report = await run_planner(snapshot, ctx)
    assert report.status == "unavailable" and ctx.budget.used["model_turn"] == 1
    assert cancelled


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {
            "choices": [
                {"recommendation_id": "fabricated", "priority": "high", "reason": "follow_up"}
            ]
        },
        {"choices": [], "action": "Prescribe a dose"},
        {"choices": [], "risk_difference": 0.9},
    ],
)
async def test_fabricated_actions_clinical_or_numerical_prose_rejected(
    snapshot, context_factory, payload
):
    ctx, _ = context_factory(
        [
            ModelResponse(tool_calls=[call("inspect_finding", "finding-gap-1")]),
            ModelResponse(structured_output=payload),
        ]
    )
    report = await run_planner(snapshot, ctx)
    assert report.status == "unavailable" and not report.recommendations


@pytest.mark.anyio
async def test_uninspected_selection_rejected(snapshot, context_factory):
    ctx, _ = context_factory()
    c = build_candidates(snapshot, ctx)[0]
    ctx.model.responses = iter([ModelResponse(text="done"), responses(c)[1]])
    report = await run_planner(snapshot, ctx)
    assert report.status == "unavailable"


@pytest.mark.anyio
async def test_every_tool_call_gets_result_including_oversized_batch(snapshot, context_factory):
    ctx, _ = context_factory()
    c = build_candidates(snapshot, ctx)[0]
    batch = [call("inspect_finding", "finding-gap-1", "ok")]
    batch += [call("send_email", "untrusted", str(i)) for i in range(6)]
    ctx.model.responses = iter([ModelResponse(tool_calls=batch), responses(c)[1]])
    report = await run_planner(snapshot, ctx)
    results = [m for m in ctx.model.calls[-1][0] if m.role == "tool"]
    assert len(results) == len(batch)
    assert all("error" in m.content["result"] for m in results[1:])
    assert report.status == "partial" and report.recommendations


def add_pair(snapshot):
    bundle = snapshot.screening.trial_bundle
    for sex in ["Female", "Male"]:
        bundle.adverse_event_rows.append(
            AdverseEventRow(
                row_id=f"row-{sex}",
                source_term="Nausea",
                group_id="arm-1",
                intervention="Synthetic drug",
                reported_sex_category=sex,
                analysis_population="Safety population",
                participants_affected=1,
                participants_at_risk=10,
                event_seriousness="non_serious",
                reporting_window="Synthetic window",
                is_synthetic=True,
                source_locator=SourceLocator(
                    source_id=bundle.sources[0].source_id, location=f"rows.{sex}"
                ),
            )
        )
    snapshot.screening.findings[0].endpoint = "Nausea"


def test_feasibility_requires_actual_compatible_rows_and_registration(snapshot, context_factory):
    add_pair(snapshot)
    ctx, _ = context_factory()
    c = build_candidates(snapshot, ctx)[0]
    assert c.category == "additional_analysis" and c.availability == "available"
    ctx.datasets.clear()
    c = build_candidates(snapshot, ctx)[0]
    assert c.category != "additional_analysis"
    ctx.datasets["same-trial-stale"] = snapshot.screening.trial_bundle.model_copy(deep=True)
    snapshot.screening.trial_bundle.adverse_event_rows[1].reporting_window = "different"
    c = build_candidates(snapshot, ctx)[0]
    assert c.category == "additional_data_collection"


@pytest.mark.parametrize(
    "field,value",
    [
        ("participants_affected", None),
        ("participants_at_risk", None),
        ("analysis_population", None),
        ("intervention", None),
        ("group_id", "different"),
    ],
)
def test_baseline_or_occurrences_never_replace_participant_prerequisites(
    snapshot, context_factory, field, value
):
    add_pair(snapshot)
    setattr(snapshot.screening.trial_bundle.adverse_event_rows[0], field, value)
    snapshot.screening.trial_bundle.adverse_event_rows[0].event_occurrences = 50
    ctx, _ = context_factory()
    c = build_candidates(snapshot, ctx)[0]
    assert c.availability == "missing" and c.category == "additional_data_collection"


@pytest.mark.anyio
async def test_completed_synthetic_snapshot_and_priority_selection(snapshot, context_factory):
    make_evidence(snapshot, "background")
    snapshot.screening.trial_bundle.limitations.clear()
    snapshot.investigation.status = "completed"
    snapshot.investigation.limitations.clear()
    ctx, _ = context_factory()
    candidates = build_candidates(snapshot, ctx)
    assert len(candidates) == 2
    ctx.model.responses = iter(responses(candidates[-1], priority="low", reason="follow_up"))
    report = await run_planner(snapshot, ctx)
    assert report.status == "completed"
    assert len(report.recommendations) == 1
    assert report.recommendations[0].priority == "low"
    assert report.recommendations[0].category == "interpretation_review"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_ids", ["fake"]),
        ("analysis_ids", ["fake"]),
        ("source_ids", ["fake"]),
        ("finding_ids", ["fake"]),
        ("hypothesis_ids", ["fake"]),
    ],
)
async def test_unknown_references_rejected(snapshot, context_factory, field, value):
    ctx, _ = context_factory()
    ctx.model.responses = iter(responses(build_candidates(snapshot, ctx)[0]))
    report = await run_planner(snapshot, ctx)
    setattr(report.recommendations[0], field, value)
    with pytest.raises(ValueError, match="Unknown"):
        validate_planner_report(report, snapshot)


@pytest.mark.anyio
async def test_known_but_unrelated_evidence_rejected(snapshot, context_factory):
    e = make_evidence(snapshot)
    snapshot.screening.findings.append(
        Finding(
            finding_id="other",
            finding_type="data_quality",
            title="Synthetic other finding",
            description="Other finding",
            priority="low",
            priority_rationale="Synthetic",
            source_ids=["source-synthetic-1"],
            is_synthetic=True,
        )
    )
    e.finding_ids = ["other"]
    ctx, _ = context_factory()
    c = build_candidates(snapshot, ctx)[0]
    sequence = responses(c)
    ctx.model.responses = iter(
        [
            sequence[0],
            ModelResponse(tool_calls=[call("inspect_finding", "other")]),
            sequence[1],
        ]
    )
    report = await run_planner(snapshot, ctx)
    report.recommendations[0].evidence_ids = [e.evidence_id]
    with pytest.raises(ValueError, match="unrelated"):
        validate_planner_report(report, snapshot)


def test_invalid_input_rejected_before_model(snapshot, context_factory):
    snapshot.investigation.trial_id = "mismatch"
    with pytest.raises(ValueError, match="trial"):
        from app.validation import validate_planner_input

        validate_planner_input(snapshot)


def test_human_review_cannot_be_disabled():
    with pytest.raises(ValidationError):
        PlannerReport(
            trial_id="synthetic",
            status="unavailable",
            is_synthetic=True,
            human_review_required=False,
        )


def test_input_limitations_preserve_zero_accepted_and_partial(snapshot):
    snapshot.evidence_reports = [EvidenceReport(request_id="empty", status="partial")]
    limits = planner_input_limitations(snapshot)
    assert any("No accepted" in x for x in limits)
    assert any("evidence research is incomplete" in x for x in limits)


def test_pk_gap_has_specific_future_protocol_alternative(snapshot, context_factory):
    snapshot.screening.findings[0].title = "Sex-stratified pharmacokinetic results unavailable"
    ctx, _ = context_factory()
    candidates = build_candidates(snapshot, ctx)
    assert {c.category for c in candidates} == {"additional_data_collection", "future_trial_design"}
    assert all("PK" in c.action for c in candidates)
    assert all(c.availability == "missing" for c in candidates)
    assert "existing sources" in candidates[-1].prerequisites[0]


def test_read_only_inspectors_reject_unknown_and_show_prerequisites(snapshot, context_factory):
    from app.agents.planner import inspect

    item = make_evidence(snapshot)
    ctx, _ = context_factory()
    candidates = build_candidates(snapshot, ctx)
    result = inspect("inspect_evidence", item.evidence_id, snapshot, ctx, candidates)
    assert result["evidence"]["relation"] == "contradicts"
    result = inspect("check_data", candidates[0].recommendation_id, snapshot, ctx, candidates)
    assert result["availability"] == "missing"
    assert "never event occurrences" in result["prerequisites"][0]
    with pytest.raises(ValueError):
        inspect("request_analysis", "unknown", snapshot, ctx, candidates)


@pytest.mark.anyio
async def test_review_mapping_prevents_available_comparison(snapshot, context_factory):
    from app.contracts import SymptomMapping

    add_pair(snapshot)
    snapshot.screening.symptom_mappings = [
        SymptomMapping(
            mapping_id="review-me",
            original_text="Synthetic ambiguous symptom",
            assertion="uncertain",
            temporality="unknown",
            needs_review=True,
            explanation="Synthetic ambiguity",
            source_locator=SourceLocator(
                source_id="source-synthetic-1", location="synthetic.description"
            ),
        )
    ]
    ctx, _ = context_factory()
    candidates = build_candidates(snapshot, ctx)
    assert candidates[0].category == "interpretation_review"
    assert all(c.category != "additional_analysis" for c in candidates)
    ctx.model.responses = iter(responses(candidates[0], reason="interpretation_first"))
    report = await run_planner(snapshot, ctx)
    assert report.status == "partial"
    assert "Symptom interpretation requires human review." in report.input_limitations


@pytest.mark.anyio
async def test_unknown_source_preview_cannot_become_evidence(snapshot, context_factory):
    from datetime import UTC, datetime

    from app.contracts import SearchRecord

    source = snapshot.screening.trial_bundle.sources[0]
    snapshot.evidence_reports = [
        EvidenceReport(
            request_id="preview-only",
            status="partial",
            sources=[source],
            searches=[
                SearchRecord(
                    service="europe_pmc",
                    query="synthetic only",
                    searched_at=datetime.now(UTC),
                    result_source_ids=[source.source_id],
                )
            ],
        )
    ]
    ctx, _ = context_factory()
    candidate = build_candidates(snapshot, ctx)[0]
    assert not candidate.evidence_ids
    ctx.model.responses = iter(responses(candidate))
    report = await run_planner(snapshot, ctx)
    assert report.status == "partial" and not report.recommendations[0].evidence_ids


@pytest.mark.anyio
async def test_unknown_input_references_fail_before_model(snapshot, context_factory):
    ctx, _ = context_factory()
    snapshot.screening.findings[0].source_ids.append("fabricated")
    with pytest.raises(ValueError, match="Unknown"):
        await run_planner(snapshot, ctx)
    assert not ctx.model.calls


@pytest.mark.anyio
async def test_duplicate_choices_rejected(snapshot, context_factory):
    ctx, _ = context_factory()
    seq = responses(build_candidates(snapshot, ctx)[0])
    seq[-1].structured_output["choices"] *= 2
    ctx.model.responses = iter(seq)
    report = await run_planner(snapshot, ctx)
    assert report.status == "unavailable"


@pytest.mark.anyio
async def test_report_trial_and_synthetic_labels_checked(snapshot, context_factory):
    ctx, _ = context_factory()
    ctx.model.responses = iter(responses(build_candidates(snapshot, ctx)[0]))
    report = await run_planner(snapshot, ctx)
    report.is_synthetic = False
    with pytest.raises(ValueError, match="synthetic"):
        validate_planner_report(report, snapshot)
    report.is_synthetic = True
    report.trial_id = "other"
    with pytest.raises(ValueError, match="trial"):
        validate_planner_report(report, snapshot)


@pytest.mark.parametrize("variant", ["complete", "partial"])
def test_saved_synthetic_examples_pass_cross_record_validation(variant):
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"
    snapshot = PlannerInput.model_validate_json(
        (root / f"planner_{variant}_input.json").read_text()
    )
    report = PlannerReport.model_validate_json(
        (root / f"planner_{variant}_output.json").read_text()
    )
    validate_planner_report(report, snapshot)
    assert report.is_synthetic and snapshot.screening.trial_bundle.is_synthetic
    assert report.status == ("completed" if variant == "complete" else "partial")


@pytest.mark.anyio
async def test_no_findings_no_invented_recommendations(snapshot, context_factory):
    snapshot.screening.findings.clear()
    snapshot.investigation.assessed_findings.clear()
    ctx, _ = context_factory()
    report = await run_planner(snapshot, ctx)
    assert report.status == "partial" and not report.recommendations
    assert not ctx.model.calls


@pytest.mark.anyio
async def test_omitted_findings_keep_report_partial_and_expose_follow_up(snapshot, context_factory):
    original = snapshot.screening.findings[0]
    snapshot.screening.findings.append(original.model_copy(update={"finding_id": "other-gap"}))
    ctx, _ = context_factory()
    c = build_candidates(snapshot, ctx)[0]
    seq = responses(c)
    ctx.model.responses = iter(
        [
            seq[0],
            ModelResponse(tool_calls=[call("inspect_finding", "other-gap")]),
            seq[1],
        ]
    )
    report = await run_planner(snapshot, ctx)
    assert report.status == "partial"
    assert any("other-gap was not selected" in q for q in report.unresolved_questions)
    assert ctx.budget.used["model_turn"] == 3


def test_candidates_are_bounded_and_high_priority_first(snapshot, context_factory):
    base = snapshot.screening.findings[0]
    snapshot.screening.findings = [
        base.model_copy(
            update={
                "finding_id": f"gap-{i}",
                "priority": "high" if i == 39 else "low",
            }
        )
        for i in range(40)
    ]
    ctx, _ = context_factory()
    candidates = build_candidates(snapshot, ctx)
    assert len(candidates) == 24
    assert candidates[0].finding_ids == ["gap-39"]


def test_unrelated_mapping_same_file_does_not_block_structured_ae(snapshot, context_factory):
    from app.contracts import SymptomMapping

    add_pair(snapshot)
    snapshot.screening.symptom_mappings = [
        SymptomMapping(
            mapping_id="unrelated-review",
            original_text="Ambiguous headache",
            assertion="uncertain",
            temporality="unknown",
            needs_review=True,
            explanation="Keep this unrelated entry flagged.",
            source_locator=SourceLocator(source_id="source-synthetic-1", location="other-row"),
        )
    ]
    ctx, _ = context_factory()
    rec = build_candidates(snapshot, ctx)[0]
    assert rec.category == "additional_analysis" and rec.availability == "available"
    assert "Symptom interpretation requires human review." in planner_input_limitations(snapshot)


def test_event_name_only_title_uses_linked_ae_rows(snapshot, context_factory):
    add_pair(snapshot)
    finding = snapshot.screening.findings[0]
    finding.title = "Female participants had a higher Nausea rate (PBO)"
    snapshot.screening.analyses[0].parameters = {"row_ids": ["ae-Female", "ae-Male"]}
    # Use actual IDs, rather than assuming the helper's naming scheme.
    snapshot.screening.analyses[0].parameters["row_ids"] = [
        row.row_id for row in snapshot.screening.trial_bundle.adverse_event_rows
    ]
    ctx, _ = context_factory()
    rec = build_candidates(snapshot, ctx)[0]
    assert rec.category == "additional_analysis"
    assert "Nausea" in rec.rationale


@pytest.mark.anyio
async def test_final_selection_lists_eligible_ids_and_reasons(snapshot, context_factory):
    ctx, _ = context_factory()
    candidate = build_candidates(snapshot, ctx)[0]
    ctx.model.responses = iter(responses(candidate))
    await run_planner(snapshot, ctx)
    messages, options = ctx.model.calls[-1]
    schema = options["output_schema"]
    assert schema["$defs"]["Choice"]["properties"]["recommendation_id"]["enum"]
    final = messages[-1].content
    assert final["eligible_choices"][0]["recommendation_id"] == candidate.recommendation_id
    assert "data_prerequisite" in final["eligible_choices"][0]["allowed_reasons"]
