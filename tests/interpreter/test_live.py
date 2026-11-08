"""Explicitly opt-in paid model test; excluded from ordinary collection runs."""

import asyncio
import os

import pytest

from app.agents.interpreter import run_interpreter
from app.config import Settings
from app.contracts import NarrativeEntry, TrialInput
from app.model_client import GeminiModelClient
from app.services.terminology import SuppliedTerminology


@pytest.mark.live
def test_live_narrative_interpretation(context_factory, screening):
    if os.environ.get("TRIALFAIR_RUN_LIVE_INTERPRETER") != "1":
        pytest.skip("Set TRIALFAIR_RUN_LIVE_INTERPRETER=1 to permit a paid model call")
    settings = Settings()
    settings.require_live_credentials()
    ctx, _ = context_factory(settings=settings)
    ctx.model = GeminiModelClient(
        api_key=settings.gemini_api_key.get_secret_value(), model_id=settings.gemini_model
    )
    ctx.terminology = SuppliedTerminology()
    bundle = screening.trial_bundle.model_copy(deep=True)
    bundle.narrative_entries = [
        NarrativeEntry(
            entry_id="live-test",
            text="No dizziness was reported",
            locator={"source_id": bundle.sources[0].source_id, "location": "synthetic.live-test"},
        )
    ]
    ctx.datasets["live-synthetic"] = bundle
    output = asyncio.run(run_interpreter(TrialInput(dataset_refs=["live-synthetic"]), ctx))
    mapping = output.symptom_mappings[0]
    assert mapping.assertion == "absent"
    assert not mapping.needs_review
    assert output.trial_bundle.is_synthetic
