"""Participant-level DM/AE loader: hand-checked synthetic examples, no clinical data."""

import asyncio

import pytest
from scipy.stats import fisher_exact

from app.contracts import AnalysisRequest, ScreeningOutput
from app.services.participant_data import ParticipantDataError, load_participant_dataset
from app.services.statistics import execute_analysis
from app.validation import validate_screening

DM_HEADER = "STUDYID,USUBJID,SEX,ARMCD,ARM,RFXSTDTC\n"
AE_HEADER = "STUDYID,USUBJID,AEDECOD,AESER,AESTDTC\n"


def write(tmp_path, dm_rows, ae_rows):
    dm = tmp_path / "dm.csv"
    ae = tmp_path / "ae.csv"
    dm.write_text(DM_HEADER + "".join(f"S,{r}\n" for r in dm_rows))
    ae.write_text(AE_HEADER + "".join(f"S,{r}\n" for r in ae_rows))
    return dm, ae


def base_dm(n_female=4, n_male=6, arm="A"):
    rows = [f"F{i},F,{arm},Drug {arm},2025-01-10" for i in range(n_female)]
    rows += [f"M{i},M,{arm},Drug {arm},2025-01-10" for i in range(n_male)]
    return rows


def rows_by(bundle):
    return {
        (r.group_id, r.source_term, r.event_seriousness, r.reported_sex_category): r
        for r in bundle.adverse_event_rows
    }


def test_unique_participants_not_event_records(tmp_path):
    ae = [
        "F0,Nausea,N,2025-01-11",
        "F0,Nausea,N,2025-01-12",
        "F0,Nausea,N,2025-01-20",
        "M0,Nausea,N,2025-01-11",
    ]
    bundle = load_participant_dataset(*write(tmp_path, base_dm(), ae), is_synthetic=True)
    female = rows_by(bundle)[("A", "Nausea", "non_serious", "Female")]
    assert (female.participants_affected, female.event_occurrences) == (1, 3)
    assert female.participants_at_risk == 4


def test_pre_existing_and_unknown_onset_are_excluded_and_disclosed(tmp_path):
    ae = [
        "F0,Insomnia,N,2024-12-01",
        "F1,Insomnia,N,2025-01-10",
        "F2,Insomnia,N,",
        "F3,Insomnia,N,2025-01",
    ]
    bundle = load_participant_dataset(*write(tmp_path, base_dm(), ae), is_synthetic=True)
    female = rows_by(bundle)[("A", "Insomnia", "non_serious", "Female")]
    # Only same-day onset (F1) is treatment-emergent; partial/missing dates are excluded.
    assert female.participants_affected == 1
    text = " ".join(bundle.limitations)
    assert "1 pre-existing" in text and "2 with missing/partial onset date" in text


def test_zero_cells_are_explicit_counts_for_treated_participants(tmp_path):
    bundle = load_participant_dataset(
        *write(tmp_path, base_dm(), ["F0,Rash,N,2025-01-15"]), is_synthetic=True
    )
    male = rows_by(bundle)[("A", "Rash", "non_serious", "Male")]
    assert (male.participants_affected, male.participants_at_risk) == (0, 6)


def test_unknown_sex_kept_separately_and_screen_failures_excluded(tmp_path):
    dm = [
        *base_dm(),
        "U0,U,A,Drug A,2025-01-10",
        "X0,F,SCRNFAIL,Screen Failure,",
        "Y0,,A,Drug A,2025-01-10",
    ]
    ae = ["U0,Nausea,N,2025-01-11", "X0,Nausea,N,2025-01-11", "ZZ,Nausea,N,2025-01-11"]
    bundle = load_participant_dataset(*write(tmp_path, dm, ae), is_synthetic=True)
    rows = rows_by(bundle)
    assert rows[("A", "Nausea", "non_serious", "Unknown")].participants_affected == 1
    assert rows[("A", "Nausea", "non_serious", "Not reported")].participants_at_risk == 1
    assert rows[("A", "Nausea", "non_serious", "Female")].participants_at_risk == 4
    assert "2 not in the safety population" in " ".join(bundle.limitations)
    labels = {r.reported_label for r in bundle.demographic_rows}
    assert labels == {"Female", "Male", "Unknown", "Not reported"}
    assert all(r.denominator == 12 for r in bundle.demographic_rows)


def test_serious_and_non_serious_rows_are_separate(tmp_path):
    ae = ["F0,Hepatic enzyme increased,Y,2025-01-11", "F1,Hepatic enzyme increased,N,2025-01-11"]
    rows = rows_by(load_participant_dataset(*write(tmp_path, base_dm(), ae), is_synthetic=True))
    assert rows[("A", "Hepatic enzyme increased", "serious", "Female")].participants_affected == 1
    assert (
        rows[("A", "Hepatic enzyme increased", "non_serious", "Female")].participants_affected == 1
    )


def test_synthetic_labels_and_provenance(tmp_path):
    bundle = load_participant_dataset(
        *write(tmp_path, base_dm(), ["F0,Nausea,N,2025-01-11"]), is_synthetic=True
    )
    validate_screening(ScreeningOutput(trial_bundle=bundle))
    assert bundle.is_synthetic and all(s.source_type == "synthetic" for s in bundle.sources)
    assert all(r.is_synthetic for r in [*bundle.adverse_event_rows, *bundle.demographic_rows])
    female = rows_by(bundle)[("A", "Nausea", "non_serious", "Female")]
    assert female.source_locator.location.startswith("ae.csv lines 2;")
    real = load_participant_dataset(
        *write(tmp_path, base_dm(), ["F0,Nausea,N,2025-01-11"]), is_synthetic=False
    )
    assert all(s.source_type == "uploaded_data" and not s.is_synthetic for s in real.sources)


@pytest.mark.parametrize(
    ("dm_rows", "message"),
    [
        (["F0,F,A,Drug A,2025-01-10", "F0,F,A,Drug A,2025-01-10"], "duplicate USUBJID"),
        (["F0,F,SCRNFAIL,Screen Failure,"], "No treated participants"),
    ],
)
def test_invalid_participant_files_rejected(tmp_path, dm_rows, message):
    with pytest.raises(ParticipantDataError, match=message):
        load_participant_dataset(*write(tmp_path, dm_rows, []), is_synthetic=True)


def test_rejects_missing_columns_and_non_csv(tmp_path):
    dm, ae = write(tmp_path, base_dm(), [])
    ae.write_text("STUDYID,USUBJID\nS,F0\n")
    with pytest.raises(ParticipantDataError, match="missing required columns"):
        load_participant_dataset(dm, ae, is_synthetic=True)
    pickle = tmp_path / "dm.pkl"
    pickle.write_bytes(b"\x80\x04")
    with pytest.raises(ParticipantDataError, match="only .csv"):
        load_participant_dataset(pickle, ae, is_synthetic=True)


def test_loaded_counts_feed_comparison_with_unknown_category_present(tmp_path, context_factory):
    context, _ = context_factory()
    dm = [*base_dm(10, 20), "U0,U,A,Drug A,2025-01-10"]
    ae = [f"F{i},Nausea,N,2025-01-11" for i in range(4)] + [
        "M0,Nausea,N,2025-01-11",
        "U0,Nausea,N,2025-01-11",
    ]
    bundle = load_participant_dataset(*write(tmp_path, dm, ae), is_synthetic=True)
    rows = rows_by(bundle)
    pair = [rows[("A", "Nausea", "non_serious", s)].row_id for s in ("Female", "Male")]
    context.datasets["participants"] = bundle

    def run(tool, parameters=None):
        return asyncio.run(
            execute_analysis(
                AnalysisRequest(
                    request_id="r1",
                    requested_by="safety",
                    tool_name=tool,
                    dataset_ref="participants",
                    parameters=parameters or {},
                    rationale="test",
                ),
                context,
            )
        )

    result = run("compare_adverse_event_rates", {"row_ids": pair})
    assert result.status == "completed" and result.is_synthetic
    assert result.results["proportions"] == [0.4, 0.05]
    assert result.results["fisher_p_value"] == pytest.approx(fisher_exact([[4, 6], [1, 19]]).pvalue)
    audit = run("audit_subgroup_availability")
    assert audit.results["comparison_availability"]["adverse_events"]["status"] == "available"


def test_verbatims_and_narratives_feed_interpretation_not_counts(tmp_path):
    dm, ae = write(tmp_path, base_dm(), [])
    ae.write_text(
        "STUDYID,USUBJID,AETERM,AEDECOD,AESER,AESTDTC\n"
        "S,F0,felt queasy,Nausea,N,2025-01-11\n"
        "S,ZZ,nauseous,Nausea,N,2025-01-11\n"
    )
    notes = tmp_path / "narratives.csv"
    notes.write_text("TEXT\nNo dizziness was reported\n")
    bundle = load_participant_dataset(dm, ae, is_synthetic=True, narratives_path=notes)
    validate_screening(ScreeningOutput(trial_bundle=bundle))
    texts = {e.entry_id: e.text for e in bundle.narrative_entries}
    # Orphan record ZZ is outside the safety population, so its verbatim is not included.
    assert texts == {
        "aeterm-line-2": "felt queasy",
        "narrative-line-2": "No dizziness was reported",
    }
    assert rows_by(bundle)[("A", "Nausea", "non_serious", "Female")].participants_affected == 1
    assert {s.source_id for s in bundle.sources} >= {"participant-narratives"}
    assert all(s.is_synthetic for s in bundle.sources)
