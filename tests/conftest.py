"""Injected fixtures shared by investigator/API tests; no real model or source calls."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.context import RunBudget, ToolContext
from app.contracts import EvidenceReport, InvestigationReport, ScreeningOutput
from app.model_client import ModelResponse

ROOT = Path(__file__).resolve().parents[1]


class ScriptedModel:
    """Test-only model: scripted responses are never substituted for live production calls."""

    model_id = "test-scripted-not-live"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def generate(self, messages, **kwargs):
        self.calls.append((list(messages), kwargs))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def screening():
    return ScreeningOutput.model_validate_json(
        (ROOT / "fixtures/synthetic/screening.json").read_text()
    )


@pytest.fixture
def investigation():
    return InvestigationReport.model_validate_json(
        (ROOT / "fixtures/synthetic/investigation.json").read_text()
    )


@pytest.fixture
def context_factory(screening):
    def create(responses=(), *, evidence_handler=None, analysis_handler=None, settings=None):
        settings = settings or Settings(_env_file=None, mode="replay")

        async def no_evidence(request, context):
            return EvidenceReport(request_id=request.request_id, status="unavailable")

        async def no_analysis(request, context):
            raise NotImplementedError("No data-compatible analysis configured")

        events = []
        context = ToolContext(
            run_id="test-run",
            settings=settings,
            model=ScriptedModel(responses),
            registry=SimpleNamespace(),
            literature=SimpleNamespace(),
            terminology=SimpleNamespace(),
            budget=RunBudget.from_settings(settings),
            emit=events.append,
            analysis_handler=analysis_handler or no_analysis,
            evidence_handler=evidence_handler or no_evidence,
            datasets={screening.trial_bundle.trial_id: screening.trial_bundle},
        )
        return context, events

    return create


@pytest.fixture
def fixture_run():
    return json.loads((ROOT / "fixtures/synthetic/run_result.json").read_text())


@pytest.fixture
def final_response(investigation):
    return ModelResponse(structured_output=investigation.model_dump(mode="json"))
