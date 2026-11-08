"""Adaptive research and grounded output with explicitly synthetic publication fakes."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.agents.evidence import (
    EvidenceDraft,
    EvidenceState,
    EvidenceSynthesis,
    compile_evidence_report,
    execute_evidence_tool,
    run_evidence,
)
from app.contracts import EvidenceItem, EvidenceRequest, PublicationRecord, SourceRecord
from app.model_client import ModelResponse, ToolCall

SUPPORT = "Synthetic women had higher exposure in the test formulation."
CONTRARY = "Synthetic study found no sex difference for a different formulation."


def publication(sid="lit-support", abstract=SUPPORT, doi=None):
    return PublicationRecord(
        source=SourceRecord(
            source_id=sid,
            source_type="publication",
            title="Synthetic publication fixture",
            retrieved_at=datetime(2026, 11, 8, tzinfo=UTC),
            content_hash="a" * 64,
            access_level="abstract" if abstract else "metadata",
            is_synthetic=True,
        ),
        abstract=abstract,
        doi=doi,
    )


class FakeLiterature:
    def __init__(self, results):
        self.results = iter(results)
        self.queries = []

    async def search_publications(self, query, *, page_size=5):
        self.queries.append(query)
        value = next(self.results)
        if isinstance(value, Exception):
            raise value
        return value


def request():
    return EvidenceRequest(
        request_id="research-1",
        trial_id="synthetic-trial-1",
        finding_ids=["finding-gap-1"],
        question="Investigate the test finding",
    )


def call(name, **args):
    return ToolCall(call_id=f"call-{name}-{len(str(args))}", name=name, arguments=args)


def calls(*items):
    return ModelResponse(tool_calls=list(items))


def item(sid="lit-support", quote=SUPPORT, relation="supports", eid="evidence-1"):
    return EvidenceItem(
        evidence_id=eid,
        source_id=sid,
        finding_ids=["finding-gap-1"],
        claim="Synthetic claim for a test only.",
        relation=relation,
        source_locator={
            "source_id": sid,
            "location": f"abstract[0:{len(quote)}]",
            "excerpt": quote,
        },
        relevance="Test-only data",
        study_design="synthetic fixture",
    )


def draft(*items):
    return ModelResponse(
        structured_output=EvidenceSynthesis(
            evidence_items=list(items),
            status="completed",
        ).model_dump(mode="json")
    )


def test_support_contradiction_and_adaptive_search(context_factory):
    support, contrary = publication(), publication("lit-contrary", CONTRARY)
    context, events = context_factory(
        [
            calls(
                call("search_publications", query="drug sex exposure"),
                call("search_publications", query="drug sex no difference"),
            ),
            calls(
                call("inspect_publication", source_id="lit-support"),
                call("inspect_publication", source_id="lit-contrary"),
            ),
            ModelResponse(text="Compare formulation differences"),
            draft(item(), item("lit-contrary", CONTRARY, "contradicts", "evidence-2")),
        ]
    )
    context.literature = FakeLiterature([[support], [contrary]])
    report = asyncio.run(run_evidence(request(), context))
    assert report.status == "completed"
    assert {x.relation for x in report.evidence_items} == {"supports", "contradicts"}
    assert len(report.searches) == 2
    assert context.budget.used["model_turn"] == 4
    assert all("Abstract-only" in " ".join(x.limitations) for x in report.evidence_items)
    assert any(x.agent == "evidence" and x.event_type == "tool_call" for x in events)
    assert context.model.calls[-1][1]["tools"] == []
    assert not context.evidence_reports  # Outer dispatcher, not Agent 3, appends the final report.


def test_query_refined_after_empty_initial_search(context_factory):
    context, _ = context_factory(
        [
            calls(call("search_publications", query="overly specific test search")),
            calls(call("search_publications", query="broader contradictory test query")),
            calls(call("inspect_publication", source_id="lit-support")),
            draft(item()),
        ]
    )
    context.literature = FakeLiterature([[], [publication()]])
    report = asyncio.run(run_evidence(request(), context))
    assert len(report.evidence_items) == 1
    assert len(context.literature.queries) == 2
    first_result = context.model.calls[1][0][-1].content["result"]
    assert first_result["count"] == 0


@pytest.mark.parametrize("change", ["source", "quote", "location", "finding"])
def test_fabricated_or_uninspected_support_rejected(change, context_factory):
    state = EvidenceState()
    record = publication()
    state.add_publication(record)
    state.register_passage(record.source, f"abstract[0:{len(SUPPORT)}]", SUPPORT)
    proposed = item()
    if change == "source":
        proposed.source_id = "made-up-paper"
    elif change == "quote":
        proposed.source_locator.excerpt = "This quotation was never retrieved."
    elif change == "location":
        proposed.source_locator.location = "unread body"
    else:
        proposed.finding_ids = ["another-finding"]
    context, _ = context_factory()
    report = compile_evidence_report(
        EvidenceDraft(evidence_items=[proposed], status="completed"), request(), context, state
    )
    assert not report.evidence_items
    assert any("Rejected" in x for x in report.limitations)
    assert report.status != "completed"


def test_search_preview_cannot_be_cited_as_reviewed(context_factory):
    state = EvidenceState()
    state.add_publication(publication())
    context, _ = context_factory()
    report = compile_evidence_report(
        EvidenceDraft(evidence_items=[item()], status="completed"), request(), context, state
    )
    assert not report.evidence_items


def test_metadata_only_cannot_establish_safety_claim(context_factory):
    state = EvidenceState()
    record = publication(abstract=None)
    state.add_publication(record)
    location = f"title[0:{len(record.source.title)}]"
    state.register_passage(record.source, location, record.source.title)
    claim = item(quote=record.source.title)
    claim.source_locator.location = location
    context, _ = context_factory()
    report = compile_evidence_report(
        EvidenceDraft(evidence_items=[claim], status="completed"), request(), context, state
    )
    assert not report.evidence_items


def test_duplicate_doi_candidates_are_collapsed():
    state = EvidenceState()
    first = state.add_publication(publication(doi="10.99999/same-test"))
    second = state.add_publication(publication("duplicate", doi="10.99999/SAME-TEST"))
    assert first == second
    assert len(state.publications) == 1


def test_trial_overlap_is_disclosed(context_factory):
    state = EvidenceState()
    for record in [publication(), publication("other")]:
        state.add_publication(record)
        state.register_passage(record.source, "abstract", "Test reports NCT12345678 results.")
    context, _ = context_factory()
    report = compile_evidence_report(EvidenceDraft(status="partial"), request(), context, state)
    assert any("NCT12345678" in x and "overlap" in x for x in report.limitations)


def test_source_failure_and_no_results_are_not_proof_of_safety(context_factory):
    context, _ = context_factory(
        [
            calls(call("search_publications", query="test question")),
            ModelResponse(),
            draft(),
        ]
    )
    context.literature = FakeLiterature([RuntimeError("provider secret should not appear")])
    report = asyncio.run(run_evidence(request(), context))
    assert report.status == "unavailable"
    assert not report.evidence_items
    assert "secret" not in report.model_dump_json()
    assert report.unresolved_questions


def test_budget_reserves_turns_for_outer_investigator(context_factory):
    context, _ = context_factory()
    context.budget.used["model_turn"] = 10
    report = asyncio.run(run_evidence(request(), context))
    assert not context.model.calls
    assert report.status == "unavailable"
    assert any("budget" in x for x in report.limitations)


def test_statistics_suggestions_returned_not_executed(context_factory):
    from app.contracts import AnalysisRequest

    context, _ = context_factory()
    suggestion = AnalysisRequest(
        request_id="suggestion-1",
        requested_by="evidence",
        tool_name="audit_subgroup_availability",
        dataset_ref="synthetic-trial-1",
        rationale="Check missing subgroup results",
        related_finding_ids=["finding-gap-1"],
    )
    report = compile_evidence_report(
        EvidenceDraft(status="partial", suggested_analysis_requests=[suggestion]),
        request(),
        context,
        EvidenceState(),
    )
    assert report.suggested_analysis_requests == [suggestion]
    assert not context.additional_analyses


def test_unknown_tool_and_unretrieved_publication_rejected(context_factory):
    context, _ = context_factory()
    for command in [
        call("fetch_arbitrary_url", url="https://example.com"),
        call("inspect_publication", source_id="unretrieved"),
    ]:
        with pytest.raises(ValueError):
            asyncio.run(execute_evidence_tool(command, request(), context, EvidenceState()))


def test_related_trials_use_injected_registry(context_factory):
    from app.contracts import TrialSearchHit

    context, _ = context_factory()
    seen = []

    async def search(query, *, page_size):
        seen.append(query)
        return [TrialSearchHit(nct_id="NCT12345678", title="Synthetic trial hit")]

    context.registry = SimpleNamespace(search_related_trials=search)
    state = EvidenceState()
    result = asyncio.run(
        execute_evidence_tool(
            call("search_related_trials", query="trial query"),
            request(),
            context,
            state,
        )
    )
    assert result["trials"][0]["nct_id"] == "NCT12345678"
    assert seen == ["trial query"]
    assert "NCT12345678" in state.trial_ids


def test_full_text_claim_uses_body_source_and_returned_passage(context_factory):
    state = EvidenceState()
    record = publication()
    record.pmcid = "PMC999999999"
    record.full_text_available = True
    state.add_publication(record)
    body = "Synthetic full body finding for a test only."
    source = record.source.model_copy(
        update={"source_id": "body-source", "access_level": "full_text"}
    )

    async def fetch(pmcid):
        assert pmcid == "PMC999999999"
        return body, source

    context, _ = context_factory()
    context.literature = SimpleNamespace(fetch_open_access_full_text=fetch)
    inspected = asyncio.run(
        execute_evidence_tool(
            call("inspect_publication", source_id="lit-support", full_text=True),
            request(),
            context,
            state,
        )
    )
    assert inspected["source"]["source_id"] == "body-source"
    evidence = item(sid="body-source", quote=body)
    evidence.source_locator.location = inspected["location"]
    report = compile_evidence_report(
        EvidenceDraft(evidence_items=[evidence], status="partial"), request(), context, state
    )
    assert report.evidence_items[0].source_id == "body-source"
    assert not any("Abstract-only" in x for x in report.evidence_items[0].limitations)


def test_same_pmid_is_deduplicated_even_when_doi_is_missing():
    state = EvidenceState()
    first = publication(doi="10.99999/test")
    first.pmid = "999999999"
    second = publication("same-pmid-no-doi")
    second.pmid = "999999999"
    assert state.add_publication(first) == state.add_publication(second)


def test_hanging_source_request_cancelled_by_shared_deadline(context_factory):
    from app.config import Settings

    context, _ = context_factory(
        [
            calls(call("search_publications", query="test question")),
        ],
        settings=Settings(_env_file=None, run_timeout_seconds=0.02),
    )
    cancelled = []

    async def hanging(*args, **kwargs):
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.append(True)

    context.literature = SimpleNamespace(search_publications=hanging)
    report = asyncio.run(run_evidence(request(), context))
    assert cancelled
    assert report.status == "unavailable"
    assert any("deadline" in x for x in report.limitations)


def test_retrieved_title_cannot_be_replaced_by_model_sources(context_factory):
    context, _ = context_factory(
        [
            calls(call("search_publications", query="test question")),
            ModelResponse(),
            ModelResponse(
                structured_output={"status": "completed", "sources": [{"title": "Invented"}]}
            ),
        ]
    )
    context.literature = FakeLiterature([[publication()]])
    report = asyncio.run(run_evidence(request(), context))
    assert report.sources[0].title == "Synthetic publication fixture"
    assert "Invented" not in report.model_dump_json()
    assert report.status == "partial"


def test_synthetic_trial_id_not_sent_to_public_literature(context_factory):
    context, _ = context_factory()
    context.literature = SimpleNamespace()
    with pytest.raises(ValueError, match="Synthetic trial"):
        asyncio.run(
            execute_evidence_tool(
                call("search_publications", query="synthetic-trial-1 results"),
                request(),
                context,
                EvidenceState(),
            )
        )


def test_evidence_ids_are_unique_across_research_requests(context_factory):
    context, _ = context_factory()
    state = EvidenceState()
    record = publication()
    state.add_publication(record)
    state.register_passage(record.source, f"abstract[0:{len(SUPPORT)}]", SUPPORT)
    first = compile_evidence_report(
        EvidenceDraft(evidence_items=[item()], status="partial"), request(), context, state
    )
    other_request = request().model_copy(update={"request_id": "another-research-request"})
    second = compile_evidence_report(
        EvidenceDraft(evidence_items=[item()], status="partial"), other_request, context, state
    )
    assert first.evidence_items[0].evidence_id != second.evidence_items[0].evidence_id


def test_last_research_turn_inspects_and_synthesis_uses_fresh_grounded_context(context_factory):
    context, _ = context_factory(
        [
            calls(call("search_publications", query="first focused query")),
            calls(call("search_publications", query="opposing results query")),
            calls(call("inspect_publication", source_id="lit-support")),
            draft(item()),
        ]
    )
    context.literature = FakeLiterature([[publication()], [publication()]])
    report = asyncio.run(run_evidence(request(), context))
    assert report.evidence_items
    last_tools = {tool.name for tool in context.model.calls[2][1]["tools"]}
    assert "inspect_publication" in last_tools
    assert "search_publications" not in last_tools
    final_messages = context.model.calls[-1][0]
    assert {message.role for message in final_messages} == {"system", "user"}
    packet = final_messages[-1].content["inspected_sources"][0]
    assert packet["passage"] == SUPPORT
    assert context.model.calls[-1][1]["tools"] == []


def test_full_text_failure_uses_explicit_abstract_fallback_and_known_pmid(context_factory):
    from app.services.europe_pmc import LiteratureUnavailable

    state = EvidenceState()
    record = publication()
    record.pmid = "999999999"
    record.pmcid = "PMC999999999"
    record.full_text_available = True
    state.add_publication(record)
    context, _ = context_factory()

    async def unavailable(pmcid):
        raise LiteratureUnavailable("Full-text service unavailable")

    context.literature = SimpleNamespace(fetch_open_access_full_text=unavailable)
    result = asyncio.run(
        execute_evidence_tool(
            call("inspect_publication", source_id="999999999", full_text=True),
            request(),
            context,
            state,
        )
    )
    assert result["review_scope"] == "abstract"
    assert result["passage"] == SUPPORT
    assert result["source"]["source_id"] == "lit-support"
    assert "abstract instead" in result["fallback"]
    report = compile_evidence_report(
        EvidenceDraft(evidence_items=[item()], status="completed"), request(), context, state
    )
    assert len(report.evidence_items) == 1
    assert report.status == "partial"


def test_final_provider_schema_has_no_recursive_or_untyped_analysis_dictionary():
    import json

    schema = EvidenceSynthesis.model_json_schema()
    assert "JsonValue" not in json.dumps(schema)
    assert "AnalysisRequest" not in schema.get("$defs", {})
    assert (
        schema["$defs"]["AnalysisSuggestion"]["properties"]["parameters_json"]["type"] == "string"
    )


def test_final_failure_reports_category_and_http_code_without_provider_text(context_factory):
    class ProviderError(RuntimeError):
        code = 400

    context, _ = context_factory(
        [
            calls(call("search_publications", query="focused query")),
            calls(call("inspect_publication", source_id="lit-support")),
            ModelResponse(),
            ProviderError("raw credential=private-value must not be logged"),
        ]
    )
    context.literature = FakeLiterature([[publication()]])
    report = asyncio.run(run_evidence(request(), context))
    assert any(
        "Final evidence synthesis" in value and "HTTP 400" in value for value in report.limitations
    )
    assert "private-value" not in report.model_dump_json()
    assert report.sources and not report.evidence_items


def test_unconfigured_registry_tools_not_offered(context_factory):
    context, _ = context_factory(
        [
            calls(call("search_publications", query="focused query")),
            calls(call("inspect_publication", source_id="lit-support")),
            ModelResponse(),
            draft(item()),
        ]
    )
    context.registry = SimpleNamespace(is_available=False)
    context.literature = FakeLiterature([[publication()]])
    report = asyncio.run(run_evidence(request(), context))
    names = {tool.name for _, options in context.model.calls for tool in options["tools"]}
    assert "search_related_trials" not in names
    assert "inspect_trial_record" not in names
    assert report.evidence_items
    assert any("literature-only" in value for value in report.limitations)
