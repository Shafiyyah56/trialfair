"""Participant-level PK, exposure-response, QTc and finding prioritisation.

Small hand-built synthetic CSVs; expected values are computed independently here with
NumPy/SciPy/statsmodels, not by reusing the code under test.
"""

import asyncio
import math
from types import SimpleNamespace

import numpy as np
import pytest
import statsmodels.api as sm
from google.genai import types
from scipy import stats

from app.agents.interpreter import run_interpreter
from app.config import Settings
from app.contracts import AnalysisRequest, TrialInput
from app.model_client import GeminiModelClient, ModelMessage
from app.services.participant_data import (
    ParticipantDataError,
    load_participant_dataset,
    participant_table_for,
)
from app.services.statistics import execute_analysis

DM = "STUDYID,USUBJID,SEX,ARMCD,ARM,RFXSTDTC\n"
AE = "STUDYID,USUBJID,AEDECOD,AESER,AESTDTC\n"
PP = "STUDYID,USUBJID,PPTESTCD,PPSTRESN,PPSTRESU\n"
EG = "STUDYID,USUBJID,EGTESTCD,EGSTRESN,EGBLFL\n"

# Two arms; placebo (P0-P9) and active (A0-A19). Active exposure rises with index and
# is higher in women; AE probability is driven by exposure (deterministic pattern).
FEMALE_ACTIVE = [f"A{i}" for i in range(8)]
MALE_ACTIVE = [f"A{i}" for i in range(8, 20)]
AUC = {
    f"A{i}": v
    for i, v in enumerate(
        [
            150,
            170,
            190,
            210,
            230,
            250,
            270,
            300,
            80,
            90,
            95,
            100,
            105,
            110,
            115,
            120,
            125,
            130,
            140,
            145,
        ]
    )
}
AFFECTED = {"A3", "A4", "A5", "A6", "A7", "A18", "A19", "A2", "P1"}


def build(tmp_path, *, pp=True, eg=False):
    dm_rows, ae_rows, pp_rows, eg_rows = [], [], [], []
    for i in range(10):
        dm_rows.append(f"S,P{i},{'F' if i < 4 else 'M'},PBO,Placebo,2025-01-10")
    for sid in FEMALE_ACTIVE + MALE_ACTIVE:
        dm_rows.append(f"S,{sid},{'F' if sid in FEMALE_ACTIVE else 'M'},ACT,Drug 10 mg,2025-01-10")
        pp_rows.append(f"S,{sid},AUCIFO,{AUC[sid]},h*ng/mL")
        pp_rows.append(f"S,{sid},CMAX,{AUC[sid] / 5},ng/mL")
    for sid in sorted(AFFECTED):
        ae_rows.append(f"S,{sid},Somnolence,N,2025-01-12")
    ae_rows.append("S,P2,Headache,N,2025-01-12")
    for i, sid in enumerate([f"P{i}" for i in range(10)] + FEMALE_ACTIVE + MALE_ACTIVE):
        female = sid in FEMALE_ACTIVE or sid in {"P0", "P1", "P2", "P3"}
        base = 420 if female else 410
        rise = 0 if sid.startswith("P") else AUC[sid] / 5 * 0.4
        eg_rows += [f"S,{sid},QTCF,{base},Y", f"S,{sid},QTCF,{base + rise + (i % 3)},N"]
    (tmp_path / "dm.csv").write_text(DM + "\n".join(dm_rows) + "\n")
    (tmp_path / "ae.csv").write_text(AE + "\n".join(ae_rows) + "\n")
    (tmp_path / "pp.csv").write_text(PP + "\n".join(pp_rows) + "\n")
    (tmp_path / "eg.csv").write_text(EG + "\n".join(eg_rows) + "\n")
    return load_participant_dataset(
        tmp_path / "dm.csv",
        tmp_path / "ae.csv",
        is_synthetic=True,
        pp_path=tmp_path / "pp.csv" if pp else None,
        eg_path=tmp_path / "eg.csv" if eg else None,
    )


def run(context, bundle, tool, parameters=None):
    context.datasets["d"] = bundle
    return asyncio.run(
        execute_analysis(
            AnalysisRequest(
                request_id="r",
                requested_by="safety",
                tool_name=tool,
                dataset_ref="d",
                parameters=parameters or {},
                rationale="test",
            ),
            context,
        )
    )


def test_pk_rows_are_geometric_means_and_kept_out_of_bundle(tmp_path):
    bundle = build(tmp_path)
    row = next(
        r for r in bundle.pk_rows if r.parameter == "AUCIFO" and r.reported_sex_category == "Female"
    )
    expected = math.exp(np.mean(np.log([AUC[s] for s in FEMALE_ACTIVE])))
    assert row.value == pytest.approx(expected, rel=1e-6)
    assert row.sample_size == 8 and row.summary_statistic == "geometric mean"
    assert bundle.availability.sex_stratified_pk == "available"
    # Participant-level values are never serialised into the shared bundle.
    assert "A0" not in bundle.model_dump_json().replace("pp.csv", "")
    assert participant_table_for(bundle).exposures["AUCIFO"]["A0"] == 150


def test_pk_loading_rejects_repeats_and_mixed_units(tmp_path):
    build(tmp_path)
    pp = tmp_path / "pp.csv"
    pp.write_text(PP + "S,A0,AUCIFO,1,h*ng/mL\nS,A0,AUCIFO,2,h*ng/mL\n")
    with pytest.raises(ParticipantDataError, match="repeats AUCIFO"):
        load_participant_dataset(
            tmp_path / "dm.csv", tmp_path / "ae.csv", is_synthetic=True, pp_path=pp
        )
    pp.write_text(PP + "S,A0,AUCIFO,1,h*ng/mL\nS,A1,AUCIFO,2,h*ug/mL\n")
    with pytest.raises(ParticipantDataError, match="more than one unit"):
        load_participant_dataset(
            tmp_path / "dm.csv", tmp_path / "ae.csv", is_synthetic=True, pp_path=pp
        )


def test_pk_ratio_matches_independent_welch(tmp_path, context_factory):
    bundle = build(tmp_path)
    context, _ = context_factory()
    result = run(context, bundle, "summarise_pk_by_sex")
    ratio = next(
        r for r in result.results["participant_level_ratios"] if r["parameter"] == "AUCIFO"
    )
    f = np.log([AUC[s] for s in FEMALE_ACTIVE])
    m = np.log([AUC[s] for s in MALE_ACTIVE])
    ci = stats.ttest_ind(f, m, equal_var=False).confidence_interval(0.95)
    assert ratio["geometric_mean_ratio"] == pytest.approx(math.exp(f.mean() - m.mean()))
    assert ratio["ratio_ci95"] == pytest.approx([math.exp(ci.low), math.exp(ci.high)])
    assert result.is_synthetic


def test_exposure_response_matches_statsmodels(tmp_path, context_factory):
    bundle = build(tmp_path)
    context, _ = context_factory()
    result = run(context, bundle, "exposure_response", {"term": "Somnolence"})
    assert result.status == "completed"
    ids = [f"P{i}" for i in range(10)] + FEMALE_ACTIVE + MALE_ACTIVE
    x = np.array([0.0 if s.startswith("P") else AUC[s] for s in ids])
    scale = float(np.median(x[x > 0]))
    y = np.array([s in AFFECTED for s in ids], dtype=float)
    fit = sm.Logit(y, sm.add_constant(x / scale)).fit(disp=0)
    got = result.results["exposure_model"]["terms"]["exposure"]
    assert got["odds_ratio"] == pytest.approx(math.exp(fit.params[1]), rel=1e-6)
    assert result.results["events"] == len(AFFECTED)
    assert result.results["sex_exposure_adjusted_model"]["status"] == "completed"
    assert any("rule of thumb" in x for x in result.limitations)


def test_exposure_response_refuses_aggregate_or_unknown_inputs(tmp_path, context_factory):
    context, _ = context_factory()
    aggregate = build(tmp_path, pp=False)
    assert run(context, aggregate, "exposure_response", {"term": "Somnolence"}).status == (
        "unavailable"
    )
    bundle = build(tmp_path)
    unknown = run(context, bundle, "exposure_response", {"term": "Vomiting"})
    assert unknown.status == "unavailable" and "Unknown AE term" in unknown.limitations[0]
    invalid = run(context, bundle, "exposure_response", {"term": "Somnolence", "path": "/x"})
    assert invalid.status == "invalid"


def test_screening_registry_bundle_has_no_participant_table(context_factory, screening):
    assert participant_table_for(screening.trial_bundle) is None


def test_qtc_summary_counts_and_slopes(tmp_path, context_factory):
    bundle = build(tmp_path, eg=True)
    context, _ = context_factory()
    result = run(context, bundle, "summarise_qtc_by_sex")
    assert result.status == "completed"
    female_active = next(
        s for s in result.results["summaries"] if s["group_id"] == "ACT" and s["sex"] == "Female"
    )
    assert female_active["n"] == 8
    assert female_active["mean_baseline_ms"] == pytest.approx(420)
    concentration = result.results["concentration_qtc"]
    # Constructed: QTc rises 0.4 ms per ng/mL in both sexes, so no slope difference.
    assert concentration["slope_ms_per_unit_male"] == pytest.approx(0.4, abs=0.05)
    low, high = concentration["slope_difference_ci95"]
    assert low < 0 < high
    assert run(context, build(tmp_path), "summarise_qtc_by_sex").status == "unavailable"


def test_screening_signals_only_clear_intervals(tmp_path, context_factory):
    bundle = build(tmp_path)
    context, _ = context_factory([RuntimeError("no model in this test")])
    context.datasets["input"] = bundle
    output = asyncio.run(
        run_interpreter(TrialInput(dataset_refs=["input"], mode="replay"), context)
    )
    titles = [f.title for f in output.findings]
    assert any(t.startswith("Female AUCIFO exposure higher") for t in titles)
    assert any(t.startswith("Somnolence risk increases with drug exposure") for t in titles)
    gap = next(f for f in output.findings if f.title.startswith("No conclusive Female/Male"))
    assert gap.finding_type == "evidence_gap" and gap.analysis_ids
    for finding in output.findings:
        if finding.finding_type == "potential_signal" and "rate (" in finding.title:
            assert "exploratory" in finding.description


def test_thinking_level_is_sent_only_when_configured():
    requests = []

    class Models:
        async def generate_content(self, **kwargs):
            requests.append(kwargs)
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(role="model", parts=[types.Part(text="ok")])
                    )
                ]
            )

    client = GeminiModelClient(
        api_key="test-only-placeholder",
        model_id="test-model",
        sdk_client=SimpleNamespace(aio=SimpleNamespace(models=Models())),
    )
    message = [ModelMessage(role="user", content="hi")]
    asyncio.run(client.generate(message, tools=[], timeout_seconds=5))
    asyncio.run(client.generate(message, tools=[], timeout_seconds=5, thinking_level="low"))
    assert requests[0]["config"].thinking_config is None
    assert requests[1]["config"].thinking_config.thinking_level == types.ThinkingLevel.LOW


def test_blank_thinking_level_setting_is_unset(monkeypatch):
    monkeypatch.setenv("TRIALFAIR_INTERPRETER_THINKING_LEVEL", "")
    assert Settings(_env_file=None).interpreter_thinking_level is None
    monkeypatch.setenv("TRIALFAIR_INTERPRETER_THINKING_LEVEL", "low")
    assert Settings(_env_file=None).interpreter_thinking_level == "low"
