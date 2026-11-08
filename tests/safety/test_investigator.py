"""Exercise actual tool dispatch, hypothesis revision and scientific reference boundaries."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.agents.safety import dispatch_tool, run_safety
from app.config import Settings
from app.contracts import AnalysisResult, EvidenceItem, EvidenceReport
from app.model_client import ModelResponse, ToolCall


def tool(name, arguments, call_id="call-1"):
    return ToolCall(call_id=call_id, name=name, arguments=arguments)


def inspect_response():
    return ModelResponse(tool_calls=[tool("inspect_finding", {"finding_id": "finding-gap-1"})])


def evidence_args():
    return {
        "request_id": "research-1",
        "trial_id": "synthetic-trial-1",
        "finding_ids": ["finding-gap-1"],
        "question": "Is subgroup evidence available?",
    }


def test_model_selects_tool_and_receives_result(screening, context_factory, final_response):
    context, events = context_factory(
        [
            inspect_response(),
            ModelResponse(text="Inspection complete"),
            final_response,
        ]
    )
    result = asyncio.run(run_safety(screening, context))
    assert result.status == "partial"
    tool_messages = [m for m in context.model.calls[1][0] if m.role == "tool"]
    assert tool_messages[0].content["result"]["finding"]["finding_id"] == "finding-gap-1"
    assert context.budget.used["model_turn"] == 3
    assert {x.event_type for x in events} >= {"tool_call", "tool_result", "revision", "stop"}
    assert context.model.calls[-1][1]["tools"] == []
    assert context.model.calls[-1][1]["output_schema"] is not None


@pytest.mark.parametrize(
    "name,args",
    [
        ("execute_python", {"code": "print(1)"}),
        ("inspect_finding", {"finding_id": "nonexistent"}),
        ("inspect_analysis", {"analysis_id": "nonexistent"}),
        ("inspect_finding", {"finding_id": "finding-gap-1", "extra": "ignored?"}),
    ],
)
def test_invalid_tools_rejected(name, args, screening, context_factory):
    context, _ = context_factory()
    with pytest.raises(ValueError):
        asyncio.run(dispatch_tool(tool(name, args), screening, context))
    assert not context.evidence_reports
    assert not context.additional_analyses


def test_fake_citation_returns_partial_unassessed_report(
    screening,
    investigation,
    context_factory,
):
    investigation.evidence_ids = ["fabricated-paper"]
    context, _ = context_factory(
        [
            inspect_response(),
            ModelResponse(),
            ModelResponse(structured_output=investigation.model_dump(mode="json")),
        ]
    )
    report = asyncio.run(run_safety(screening, context))
    assert report.status == "partial"
    assert not report.assessed_findings
    assert "rejected" in report.limitations[0]
    assert not report.evidence_ids


def test_request_analysis_uses_registered_data_and_keeps_result(screening, context_factory):
    async def analyse(request, context):
        return AnalysisResult(
            analysis_id="additional-1",
            request_id=request.request_id,
            status="completed",
            method="Documented deterministic audit",
            source_locators=screening.analyses[0].source_locators,
            is_synthetic=True,
        )

    context, _ = context_factory(analysis_handler=analyse)
    args = {
        "request_id": "analysis-request-1",
        "requested_by": "safety",
        "tool_name": "audit_subgroup_availability",
        "dataset_ref": "synthetic-trial-1",
        "rationale": "Check availability",
        "related_finding_ids": ["finding-gap-1"],
    }
    result = asyncio.run(dispatch_tool(tool("request_analysis", args), screening, context))
    assert result["analysis_id"] == "additional-1"
    assert context.budget.used["additional_analysis"] == 1
    assert len(context.additional_analyses) == 1
    with pytest.raises(ValueError, match="Repeated"):
        asyncio.run(dispatch_tool(tool("request_analysis", args), screening, context))


def test_arbitrary_dataset_path_rejected_before_handler(screening, context_factory):
    context, _ = context_factory()
    args = {
        "request_id": "a",
        "requested_by": "safety",
        "tool_name": "summarise_representation",
        "dataset_ref": "/tmp/arbitrary.csv",
        "rationale": "Read a path",
    }
    with pytest.raises(ValueError, match="registered dataset"):
        asyncio.run(dispatch_tool(tool("request_analysis", args), screening, context))
    assert not context.budget.used


def test_evidence_failure_retains_unavailable_report(screening, context_factory):
    async def broken(request, context):
        raise RuntimeError("Sensitive provider URL / key must never be displayed")

    context, _ = context_factory(evidence_handler=broken)
    value = asyncio.run(
        dispatch_tool(tool("request_evidence", evidence_args()), screening, context)
    )
    assert value["status"] == "unavailable"
    assert len(context.evidence_reports) == 1
    assert "Sensitive" not in str(value)


def test_contradiction_changes_hypothesis_and_remains_visible(
    screening,
    investigation,
    context_factory,
):
    source = screening.trial_bundle.sources[0]

    async def research(request, context):
        return EvidenceReport(
            request_id=request.request_id,
            status="completed",
            sources=[source],
            evidence_items=[
                EvidenceItem(
                    evidence_id="contradiction-1",
                    source_id=source.source_id,
                    finding_ids=["finding-gap-1"],
                    claim="Synthetic opposing evidence for an interface test only.",
                    relation="contradicts",
                    source_locator=screening.analyses[0].source_locators[0],
                    relevance="Synthetic test, not a scientific conclusion.",
                )
            ],
        )

    investigation.evidence_ids = ["contradiction-1"]
    from app.contracts import Hypothesis

    investigation.hypotheses = [
        Hypothesis(
            hypothesis_id="hypothesis-1",
            statement="Hypothesis weakened by retrieved evidence.",
            finding_ids=["finding-gap-1"],
            contradicting_evidence_ids=["contradiction-1"],
            status="weakened",
        )
    ]
    context, _ = context_factory(
        [
            ModelResponse(tool_calls=[tool("request_evidence", evidence_args())]),
            ModelResponse(text="Contradiction requires revision"),
            ModelResponse(structured_output=investigation.model_dump(mode="json")),
        ],
        evidence_handler=research,
    )
    report = asyncio.run(run_safety(screening, context))
    assert report.hypotheses[0].status == "weakened"
    assert report.hypotheses[0].contradicting_evidence_ids == ["contradiction-1"]
    returned = context.model.calls[1][0][-1].content["result"]
    assert returned["evidence_items"][0]["relation"] == "contradicts"


def test_exhausted_budget_never_calls_model(screening, context_factory):
    context, _ = context_factory()
    context.budget.used["model_turn"] = context.budget.limits["model_turn"]
    report = asyncio.run(run_safety(screening, context))
    assert report.status == "partial"
    assert not context.model.calls
    assert "budget" in report.limitations[0]


def test_shared_deadline_cancels_hanging_model(screening, context_factory):
    settings = Settings(_env_file=None, run_timeout_seconds=0.02)
    context, _ = context_factory(settings=settings)
    cancelled = []

    async def hanging(*args, **kwargs):
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.append(True)

    context.model.generate = hanging
    started = datetime.now(UTC)
    report = asyncio.run(run_safety(screening, context))
    assert (datetime.now(UTC) - started).total_seconds() < 1
    assert cancelled
    assert report.status == "partial"


def test_model_exception_is_not_leaked(screening, context_factory):
    context, _ = context_factory([RuntimeError("credential=secret")])
    report = asyncio.run(run_safety(screening, context))
    assert "secret" not in report.model_dump_json()
    assert not report.hypotheses


def test_analysis_with_unknown_provenance_not_accepted(screening, context_factory):
    async def bad_analysis(request, context):
        return AnalysisResult(
            analysis_id="invalid",
            request_id=request.request_id,
            method="audit",
            status="completed",
            source_locators=[{"source_id": "fabricated-source", "location": "table-1"}],
            is_synthetic=True,
        )

    context, _ = context_factory(analysis_handler=bad_analysis)
    args = {
        "request_id": "a",
        "requested_by": "safety",
        "tool_name": "summarise_representation",
        "dataset_ref": "synthetic-trial-1",
        "rationale": "Check representation",
    }
    with pytest.raises(ValueError, match="source ID"):
        asyncio.run(dispatch_tool(tool("request_analysis", args), screening, context))
    assert not context.additional_analyses


def test_unavailable_evidence_downgrades_completed_claim(
    screening,
    investigation,
    context_factory,
):
    investigation.status = "completed"
    context, _ = context_factory(
        [
            ModelResponse(tool_calls=[tool("request_evidence", evidence_args())]),
            ModelResponse(),
            ModelResponse(structured_output=investigation.model_dump(mode="json")),
        ]
    )
    report = asyncio.run(run_safety(screening, context))
    assert report.status == "partial"
    assert context.evidence_reports[0].status == "unavailable"


def test_new_analysis_ids_available_in_final_planner(
    screening,
    investigation,
    context_factory,
):
    from app.orchestrator import investigate_screening

    async def analyse(request, context):
        return AnalysisResult(
            analysis_id="additional-1",
            request_id=request.request_id,
            status="completed",
            method="availability audit",
            source_locators=screening.analyses[0].source_locators,
            is_synthetic=True,
        )

    request = {
        "request_id": "a",
        "requested_by": "safety",
        "tool_name": "audit_subgroup_availability",
        "dataset_ref": "synthetic-trial-1",
        "rationale": "Confirm availability",
    }
    investigation.completed_analysis_ids.append("additional-1")
    context, _ = context_factory(
        [
            ModelResponse(tool_calls=[tool("request_analysis", request)]),
            ModelResponse(),
            ModelResponse(structured_output=investigation.model_dump(mode="json")),
        ],
        analysis_handler=analyse,
    )
    result = asyncio.run(investigate_screening(screening, context, mode="replay"))
    assert "additional-1" in {x.analysis_id for x in result.planner_input.screening.analyses}
    assert "additional-1" in result.investigation.completed_analysis_ids
    assert len(result.screening.analyses) == 2


def test_report_without_tool_work_cannot_claim_completed(
    screening,
    investigation,
    context_factory,
):
    investigation.status = "completed"
    context, _ = context_factory(
        [
            ModelResponse(text="No tool selected"),
            ModelResponse(structured_output=investigation.model_dump(mode="json")),
        ]
    )
    report = asyncio.run(run_safety(screening, context))
    assert report.status == "partial"


def test_unavailable_analysis_not_reported_as_completed(
    screening,
    investigation,
    context_factory,
):
    screening.analyses[0].status = "unavailable"
    context, _ = context_factory(
        [
            inspect_response(),
            ModelResponse(),
            ModelResponse(structured_output=investigation.model_dump(mode="json")),
        ]
    )
    report = asyncio.run(run_safety(screening, context))
    assert not report.completed_analysis_ids
    assert "rejected" in report.limitations[0]


def test_contradictory_evidence_cannot_be_silently_dropped(
    screening,
    investigation,
    context_factory,
):
    from app.agents.safety import validate_report
    from app.contracts import Hypothesis

    item = EvidenceItem(
        evidence_id="contrary",
        source_id=screening.trial_bundle.sources[0].source_id,
        finding_ids=["finding-gap-1"],
        claim="Synthetic contradiction, not real evidence.",
        relation="contradicts",
        source_locator=screening.analyses[0].source_locators[0],
        relevance="Test evidence preservation",
    )
    context, _ = context_factory()
    context.evidence_reports.append(
        EvidenceReport(
            request_id="research",
            evidence_items=[item],
            status="completed",
        )
    )
    investigation.hypotheses = [
        Hypothesis(
            hypothesis_id="h",
            statement="An unchallenged hypothesis",
            finding_ids=["finding-gap-1"],
            status="supported",
        )
    ]
    with pytest.raises(ValueError, match="contradictory evidence"):
        validate_report(investigation, screening, context)
