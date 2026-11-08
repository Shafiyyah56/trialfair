"""Search breadth and oversized provider batches must not prevent grounded synthesis."""

import asyncio

from app.agents.evidence import EvidenceState, execute_evidence_tool, run_evidence
from app.model_client import ModelResponse, ToolCall
from tests.evidence.test_agent import (
    FakeLiterature,
    call,
    calls,
    draft,
    item,
    publication,
    request,
)


def test_oversized_inspection_batch_retains_claim_and_complete_tool_history(context_factory):
    context, _ = context_factory(
        [
            calls(
                call("search_publications", query="support"),
                call("search_publications", query="opposing"),
            ),
            calls(
                *[
                    ToolCall(
                        call_id=f"inspect-{i}",
                        name="inspect_publication",
                        arguments={"source_id": "lit-support"},
                    )
                    for i in range(8)
                ]
            ),
            ModelResponse(),
            draft(item()),
        ]
    )
    context.literature = FakeLiterature([[publication()], [publication()]])
    report = asyncio.run(run_evidence(request(), context))
    assert report.status == "partial"
    assert len(report.evidence_items) == 1
    assert any("batch exceeded" in value for value in report.limitations)
    # Search is closed early, and reading publications is required before registry work.
    assert {t.name for t in context.model.calls[1][1]["tools"]} == {"inspect_publication"}
    history = context.model.calls[2][0]
    results = [
        m.content
        for m in history
        if m.role == "tool" and m.content["call_id"].startswith("inspect-")
    ]
    assert len(results) == 8
    assert sum("error" not in r["result"] for r in results) == 5
    assert context.model.calls[-1][1]["output_schema"] is not None


def test_search_cap_does_not_make_an_extra_source_request(context_factory):
    context, _ = context_factory()
    context.literature = FakeLiterature([[publication()]] * 3)
    state = EvidenceState()

    async def scenario():
        for i in range(3):
            await execute_evidence_tool(
                call("search_publications", query=f"query {i}"), request(), context, state
            )
        return await execute_evidence_tool(
            call("search_publications", query="excess query"), request(), context, state
        )

    result = asyncio.run(scenario())
    assert "limit reached" in result["error"]
    assert len(context.literature.queries) == len(state.searches) == 3
    assert result["retrieved_source_ids"] == ["lit-support"]


def test_full_publication_pool_returns_retained_candidates_without_value_error(context_factory):
    context, _ = context_factory()
    state = EvidenceState()
    for i in range(19):
        state.add_publication(publication(f"existing-{i}"))
    context.literature = FakeLiterature([[publication(f"new-{i}") for i in range(3)]])
    result = asyncio.run(
        execute_evidence_tool(
            call("search_publications", query="last query"), request(), context, state
        )
    )
    assert len(state.publications) == 20
    assert result["count"] == 1
    assert state.searches[0].result_source_ids == ["new-0"]
    assert any("pool is full" in value for value in state.limitations)
