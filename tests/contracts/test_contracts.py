"""Scientific data-shape and cross-agent compatibility tests; no model/network calls."""

import json
from pathlib import Path
from time import monotonic

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import create_app
from app.config import Settings
from app.context import BudgetExceeded, RunBudget
from app.contracts import (
    AdverseEventRow,
    AnalysisRequest,
    EvidenceReport,
    EvidenceRequest,
    InvestigationReport,
    PlannerInput,
    RunResult,
    ScreeningOutput,
    SourceRecord,
    SymptomMapping,
    TrialInput,
)
from app.runtime import RuntimeNotReady
from app.validation import validate_planner_input, validate_run, validate_screening

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"


def load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize(
    ("filename", "model"),
    [
        ("trial_input.json", TrialInput),
        ("screening.json", ScreeningOutput),
        ("evidence_request.json", EvidenceRequest),
        ("evidence_report.json", EvidenceReport),
        ("investigation.json", InvestigationReport),
        ("planner_input.json", PlannerInput),
        ("run_result.json", RunResult),
    ],
)
def test_fixtures_roundtrip(filename, model):
    value = model.model_validate(load(filename))
    assert model.model_validate_json(value.model_dump_json()) == value


def test_cross_agent_references():
    validate_planner_input(PlannerInput.model_validate(load("planner_input.json")))
    validate_run(RunResult.model_validate(load("run_result.json")))


@pytest.mark.parametrize("value", [{}, {"nct_id": "NCT12"}, {"nct_id": "NCT12345678", "typo": 1}])
def test_invalid_inputs_rejected(value):
    with pytest.raises(ValidationError):
        TrialInput.model_validate(value)


def test_nct_identifier():
    assert TrialInput(nct_id="NCT12345678").nct_id == "NCT12345678"


def test_no_fabricated_analysis_reference():
    value = load("screening.json")
    value["findings"][0]["analysis_ids"] = ["made-up-analysis"]
    with pytest.raises(ValueError, match="Unknown analysis ID"):
        validate_screening(ScreeningOutput.model_validate(value))


def test_no_fabricated_source_reference():
    value = load("screening.json")
    value["analyses"][0]["source_locators"][0]["source_id"] = "made-up-source"
    with pytest.raises(ValueError, match="Unknown source ID"):
        validate_screening(ScreeningOutput.model_validate(value))


def test_no_fabricated_investigator_citation():
    value = load("planner_input.json")
    value["investigation"]["evidence_ids"] = ["made-up-paper"]
    with pytest.raises(ValueError, match="Unknown evidence ID"):
        validate_planner_input(PlannerInput.model_validate(value))


def test_synthetic_label_propagates():
    value = load("screening.json")
    value["findings"][0]["is_synthetic"] = False
    with pytest.raises(ValueError, match="Synthetic findings"):
        validate_screening(ScreeningOutput.model_validate(value))


def test_synthetic_source_requires_label():
    source = load("screening.json")["trial_bundle"]["sources"][0]
    source["is_synthetic"] = False
    with pytest.raises(ValidationError):
        SourceRecord.model_validate(source)


def test_duplicate_ids_rejected():
    value = load("screening.json")
    value["analyses"] *= 2
    with pytest.raises(ValueError, match="Duplicate analysis_id"):
        validate_screening(ScreeningOutput.model_validate(value))


def test_planner_snapshot_cannot_be_stale():
    value = load("run_result.json")
    value["investigation"]["limitations"].append("Updated conclusion")
    with pytest.raises(ValueError, match="PlannerInput must match"):
        validate_run(RunResult.model_validate(value))


def test_occurrences_do_not_create_participant_counts():
    locator = load("screening.json")["analyses"][0]["source_locators"][0]
    row = AdverseEventRow(
        row_id="row-1",
        source_term="nausea",
        group_id="arm-a",
        event_occurrences=8,
        source_locator=locator,
        is_synthetic=True,
    )
    assert row.participants_affected is None
    assert row.participants_at_risk is None
    assert row.reported_sex_category is None


@pytest.mark.parametrize("affected,at_risk", [(5, 4), (-1, 4), (1.5, 4), (True, 4)])
def test_invalid_participant_counts(affected, at_risk):
    locator = load("screening.json")["analyses"][0]["source_locators"][0]
    with pytest.raises(ValidationError):
        AdverseEventRow(
            row_id="row-1",
            source_term="nausea",
            group_id="arm-a",
            participants_affected=affected,
            participants_at_risk=at_risk,
            source_locator=locator,
            is_synthetic=True,
        )


def test_negated_symptom_remains_distinct_from_count_data():
    locator = load("screening.json")["analyses"][0]["source_locators"][0]
    mapping = SymptomMapping(
        mapping_id="mapping-1",
        original_text="No dizziness reported",
        normalised_term="dizziness",
        assertion="absent",
        temporality="unknown",
        needs_review=False,
        explanation="Explicit negation in source.",
        source_locator=locator,
    )
    assert mapping.assertion == "absent"
    assert "participants_affected" not in mapping.model_dump()


def test_only_allowlisted_statistics_tools():
    with pytest.raises(ValidationError):
        AnalysisRequest(
            request_id="request-1",
            requested_by="safety",
            tool_name="execute_python",
            dataset_ref="synthetic-trial-1",
            rationale="Forbidden arbitrary execution",
        )


def test_missing_subgroup_data_has_no_sex_difference():
    screening = ScreeningOutput.model_validate(load("screening.json"))
    assert screening.trial_bundle.availability.sex_stratified_ae == "missing"
    assert all(x.finding_type == "evidence_gap" for x in screening.findings)
    assert "risk_ratio" not in screening.analyses[0].results


def test_budget_is_cumulative():
    budget = RunBudget(deadline=monotonic() + 10, limits={"model_turn": 1})
    budget.consume("model_turn")
    with pytest.raises(BudgetExceeded, match="model_turn"):
        budget.consume("model_turn")
    assert budget.used["model_turn"] == 1


def test_deadline_blocks_tools():
    budget = RunBudget(deadline=monotonic() - 1, limits={"external_request": 5})
    with pytest.raises(BudgetExceeded, match="deadline"):
        budget.consume("external_request")
    assert not budget.used


def test_settings_need_no_key_until_live_execution(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    settings = Settings(_env_file=None)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        settings.require_live_credentials()
    Settings(_env_file=None, TRIALFAIR_MODE="replay").require_live_credentials()
    assert RunBudget.from_settings(settings).limits["model_turn"] == 12


def test_health_and_unconfigured_runtime():
    def unconfigured(*args):
        raise RuntimeNotReady("Test runtime is intentionally unconfigured")

    client = TestClient(create_app(context_factory=unconfigured))
    assert client.get("/health").json()["agents_implemented"] is True
    assert client.post("/runs", json={}).status_code == 422
    assert client.post("/runs", json={"nct_id": "NCT12345678"}).status_code == 503
    assert client.get("/runs/unknown").status_code == 404
