import asyncio

import pytest

from app.agents.interpreter import run_interpreter
from app.contracts import NarrativeEntry, SymptomMapping, TrialInput
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
    mapping = SymptomMapping(
        mapping_id="mapping",
        original_text=text,
        normalised_term=term,
        assertion=assertion,
        temporality=temporality,
        needs_review=review,
        explanation="Scripted interpretation fixture, not live Gemini",
        source_locator=entry.locator,
    )
    ctx, events = context_factory(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(call_id="call", name="source_context", arguments={"entry_id": "entry"})
                ]
            ),
            ModelResponse(text="Ready"),
            ModelResponse(structured_output={"mappings": [mapping.model_dump(mode="json")]}),
        ]
    )
    ctx.terminology = SuppliedTerminology()
    output = asyncio.run(run_interpreter(TrialInput(narrative_entries=[entry], mode="replay"), ctx))
    validate_screening(output)
    assert output.symptom_mappings == [mapping]
    assert not output.trial_bundle.adverse_event_rows
    assert output.trial_bundle.sources[0].source_type == "uploaded_data"
    assert any(e.event_type == "tool_result" for e in events)
    assert ctx.budget.used["model_turn"] == 3
    assert any("Replay" in x for x in output.trial_bundle.limitations)


@pytest.mark.parametrize(
    "failure", ["fabricated-code", "changed-source", "unknown-tool", "omitted"]
)
def test_invalid_model_outputs_require_review(context_factory, failure):
    entry = NarrativeEntry(
        entry_id="entry", text="Felt sick", locator={"source_id": "uploaded", "location": "text"}
    )
    mapping = SymptomMapping(
        mapping_id="mapping",
        original_text=entry.text,
        assertion="uncertain",
        temporality="unknown",
        needs_review=True,
        explanation="Test",
        source_locator=entry.locator,
    )
    if failure == "fabricated-code":
        mapping.terminology_system, mapping.terminology_code = "MedDRA", "invented"
    if failure == "changed-source":
        mapping.original_text = "Vomiting"
    responses = [
        ModelResponse(text="Ready"),
        ModelResponse(
            structured_output={
                "mappings": [] if failure == "omitted" else [mapping.model_dump(mode="json")]
            }
        ),
    ]
    if failure == "unknown-tool":
        responses = [
            ModelResponse(tool_calls=[ToolCall(call_id="bad", name="send_email", arguments={})])
        ]
    ctx, _ = context_factory(responses)
    output = asyncio.run(run_interpreter(TrialInput(narrative_entries=[entry], mode="replay"), ctx))
    assert output.symptom_mappings[0].needs_review
    assert output.symptom_mappings[0].original_text == entry.text
    assert output.symptom_mappings[0].terminology_code is None
    assert any("incomplete" in s for s in output.trial_bundle.limitations)
    assert output.analyses


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

    from app.services.clinical_trials import ClinicalTrialsClient

    async def check():
        ctx, _ = context_factory([RuntimeError("Model not configured for this offline test")])
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=(PUBLIC / "NCT04280705.json").read_bytes())
            )
        ) as http:
            ctx.registry = ClinicalTrialsClient(http, ctx.budget)
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
