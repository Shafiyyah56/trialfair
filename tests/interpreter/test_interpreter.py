import asyncio

import pytest

from app.agents.interpreter import run_interpreter
from app.contracts import NarrativeEntry, TrialInput
from app.model_client import ModelResponse, ToolCall
from app.services.terminology import SuppliedTerminology
from app.validation import validate_screening


@pytest.mark.parametrize(
    ("text", "assertion", "temporality", "term", "review"),
    [
        ("No dizziness was reported", "absent", "unknown", "dizziness", False),
        (
            "Possible dizziness after the first dose",
            "uncertain",
            "treatment_emergent",
            "dizziness",
            True,
        ),
        ("History of nausea before enrolment", "present", "pre_existing", "nausea", False),
        ("Felt sick", "uncertain", "unknown", None, True),
    ],
)
def test_source_preserving_interpretation(
    context_factory, text, assertion, temporality, term, review
):
    entry = NarrativeEntry(
        entry_id="entry", text=text, locator={"source_id": "uploaded", "location": "text[0:]"}
    )
    judgement = {
        "entry_id": "t1",
        "normalised_term": term,
        "assertion": assertion,
        "temporality": temporality,
        "needs_review": review,
        "explanation": "Scripted interpretation fixture, not live Gemini",
    }
    responses = [ModelResponse(structured_output={"judgements": [judgement]})]
    if review:
        # Flagged texts get one bounded follow-up in which the model selects a tool.
        responses += [
            ModelResponse(
                tool_calls=[
                    ToolCall(call_id="call", name="source_context", arguments={"entry_id": "t1"})
                ]
            ),
            ModelResponse(structured_output={"judgements": [judgement]}),
        ]
    ctx, events = context_factory(responses)
    ctx.terminology = SuppliedTerminology()
    output = asyncio.run(run_interpreter(TrialInput(narrative_entries=[entry], mode="replay"), ctx))
    validate_screening(output)
    [mapping] = output.symptom_mappings
    # Python, not the model, attaches the exact source wording and locator.
    assert mapping.original_text == text and mapping.source_locator == entry.locator
    assert (mapping.assertion, mapping.temporality, mapping.normalised_term) == (
        assertion,
        temporality,
        term,
    )
    assert mapping.needs_review is review
    assert not output.trial_bundle.adverse_event_rows
    assert output.trial_bundle.sources[0].source_type == "uploaded_data"
    assert any(e.event_type == "tool_result" for e in events) is review
    assert ctx.budget.used["model_turn"] == (3 if review else 1)
    assert any("Replay" in x for x in output.trial_bundle.limitations)


@pytest.mark.parametrize("failure", ["fabricated-code", "invented-entry", "omitted", "no-output"])
def test_invalid_model_outputs_require_review(context_factory, failure):
    entry = NarrativeEntry(
        entry_id="entry", text="Felt sick", locator={"source_id": "uploaded", "location": "text"}
    )
    judgement = {
        "entry_id": "t1",
        "assertion": "uncertain",
        "temporality": "unknown",
        "needs_review": True,
        "explanation": "Test",
    }
    if failure == "fabricated-code":
        judgement |= {"terminology_system": "MedDRA", "terminology_code": "invented"}
    if failure == "invented-entry":
        judgement["entry_id"] = "t9"
    output_payload = {"judgements": [] if failure == "omitted" else [judgement]}
    response = (
        ModelResponse(text="Ready")
        if failure == "no-output"
        else ModelResponse(structured_output=output_payload)
    )
    ctx, _ = context_factory([response])
    output = asyncio.run(run_interpreter(TrialInput(narrative_entries=[entry], mode="replay"), ctx))
    assert output.symptom_mappings[0].needs_review
    assert output.symptom_mappings[0].original_text == entry.text
    assert output.symptom_mappings[0].terminology_code is None
    assert any("incomplete" in s for s in output.trial_bundle.limitations)
    assert output.analyses


def test_unsupported_followup_tool_keeps_first_pass_flagged(context_factory):
    entry = NarrativeEntry(
        entry_id="entry", text="Felt sick", locator={"source_id": "uploaded", "location": "text"}
    )
    first = {
        "entry_id": "t1",
        "assertion": "uncertain",
        "temporality": "unknown",
        "needs_review": True,
        "explanation": "Ambiguous",
    }
    ctx, _ = context_factory(
        [
            ModelResponse(structured_output={"judgements": [first]}),
            ModelResponse(tool_calls=[ToolCall(call_id="bad", name="send_email", arguments={})]),
        ]
    )
    output = asyncio.run(run_interpreter(TrialInput(narrative_entries=[entry], mode="replay"), ctx))
    [mapping] = output.symptom_mappings
    assert mapping.needs_review and mapping.normalised_term is None
    assert any("Follow-up interpretation" in s for s in output.trial_bundle.limitations)


TEXTS = ["Nausea", "  NAUSEA ", "nausea", "nauseous", "?nausea"]


def test_identical_texts_are_judged_once_but_mapped_per_entry(context_factory):
    entries = [
        NarrativeEntry(
            entry_id=f"e{i}", text=text, locator={"source_id": f"up{i}", "location": f"t[{i}]"}
        )
        for i, text in enumerate(TEXTS)
    ]
    judgements = [
        {
            "entry_id": tid,
            "normalised_term": "nausea",
            "assertion": "present",
            "temporality": "unknown",
            "needs_review": False,
            "explanation": "Stated.",
        }
        for tid in ("t1", "t2", "t3")
    ]
    ctx, _ = context_factory([ModelResponse(structured_output={"judgements": judgements})])
    output = asyncio.run(run_interpreter(TrialInput(narrative_entries=entries, mode="replay"), ctx))
    sent = ctx.model.calls[0][0][1].content["entries"]
    # Case/whitespace variants share one judgement; punctuation and wording do not.
    assert [e["text"] for e in sent] == ["Nausea", "nauseous", "?nausea"]
    # Every entry keeps its own mapping, locator and exact original wording.
    assert [m.original_text for m in output.symptom_mappings] == [
        "Nausea",
        "  NAUSEA ",
        "nausea",
        "nauseous",
        "?nausea",
    ]
    assert [m.source_locator.location for m in output.symptom_mappings] == [
        "t[0]",
        "t[1]",
        "t[2]",
        "t[3]",
        "t[4]",
    ]
    assert len({m.mapping_id for m in output.symptom_mappings}) == 5


def test_budget_preserves_deterministic_screening(context_factory):
    entry = NarrativeEntry(
        entry_id="e",
        text="Uncertain symptom",
        locator={"source_id": "uploaded", "location": "text"},
    )
    ctx, events = context_factory()
    ctx.budget.limits["model_turn"] = 0
    output = asyncio.run(run_interpreter(TrialInput(narrative_entries=[entry], mode="replay"), ctx))
    assert len(output.analyses) == 3
    assert output.symptom_mappings[0].needs_review
    assert any(e.event_type == "stop" for e in events)


def test_dataset_only_missing_subgroups(context_factory, screening):
    ctx, _ = context_factory()
    output = asyncio.run(
        run_interpreter(
            TrialInput(dataset_refs=[screening.trial_bundle.trial_id], mode="replay"), ctx
        )
    )
    validate_screening(output)
    assert output.findings[0].finding_type == "evidence_gap"
    assert output.findings[0].is_synthetic
    assert not ctx.model.calls
    assert len(ctx.datasets) == 2


def test_unknown_datasets_and_mode_mismatch(context_factory):
    ctx, _ = context_factory()
    with pytest.raises(ValueError, match="dataset_ref"):
        asyncio.run(run_interpreter(TrialInput(dataset_refs=["/etc/passwd"], mode="replay"), ctx))
    with pytest.raises(ValueError, match="mode"):
        asyncio.run(run_interpreter(TrialInput(dataset_refs=["some-dataset"]), ctx))


def test_real_nct_to_valid_screening(context_factory):
    import json

    import httpx
    from test_registry import PUBLIC

    from app.contracts import SourceRecord
    from app.services.clinical_trials import ClinicalTrialsClient

    async def check():
        ctx, _ = context_factory([RuntimeError("Model not configured for this offline test")])
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=(PUBLIC / "NCT04280705.json").read_bytes())
            )
        ) as http:
            ctx.registry = ClinicalTrialsClient(http, ctx.budget)
            metadata = json.loads((PUBLIC / "NCT04280705.provenance.json").read_text())
            ctx.registry.load_capture(
                (PUBLIC / "NCT04280705.json").read_bytes(),
                SourceRecord(
                    source_id="captured-NCT04280705",
                    source_type="trial_registry",
                    title="Captured NCT04280705",
                    external_id="NCT04280705",
                    url=metadata["url"],
                    retrieved_at=metadata["retrieved_at"],
                    content_hash=metadata["sha256"],
                    access_level="full_text",
                    is_synthetic=False,
                ),
            )
            output = await run_interpreter(TrialInput(nct_id="NCT04280705", mode="replay"), ctx)
        validate_screening(output)
        assert not output.trial_bundle.is_synthetic
        assert any(f.finding_type == "evidence_gap" for f in output.findings)
        assert all("risk_difference" not in a.results for a in output.analyses)
        # Every finding source resolves to the actual captured registry response.
        assert {s.source_id for s in output.trial_bundle.sources} == set(
            output.findings[0].source_ids
        )
        assert json.loads(output.model_dump_json())["trial_bundle"]["trial_id"] == "NCT04280705"

    asyncio.run(check())


def test_terminology_default_is_empty():
    assert asyncio.run(SuppliedTerminology().lookup("Felt sick")) == []


def test_synthetic_comparison_becomes_sourced_candidate(context_factory, screening):
    from test_statistics import counts

    ctx, _ = context_factory([RuntimeError("No model in this synthetic test")])
    ctx.datasets["synthetic-counts"] = counts(screening.trial_bundle)
    output = asyncio.run(
        run_interpreter(TrialInput(dataset_refs=["synthetic-counts"], mode="replay"), ctx)
    )
    validate_screening(output)
    candidate = next(f for f in output.findings if f.finding_type == "potential_signal")
    assert candidate.is_synthetic and candidate.analysis_ids
    analysis = next(a for a in output.analyses if a.analysis_id == candidate.analysis_ids[0])
    assert analysis.results["risk_difference"] == pytest.approx(0.1)
