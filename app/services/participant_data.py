"""Agent 1: deterministic loader for participant-level SDTM-style DM/AE CSV files.

Turns one-row-per-participant demographics and one-row-per-record adverse events into
the shared TrialBundle aggregate rows (per arm x reported sex x term x seriousness),
so the existing allowlisted statistics tools can run on them. Python does the counting;
no model is involved.

Scientific rules applied here:
- Safety population = participants with a recorded first-dose date in a treated arm.
  Screen failures and undosed participants are excluded from denominators and events.
- Treatment-emergent = onset on or after the first-dose date. Earlier onset is
  pre-existing and excluded. Missing or partial onset dates are excluded and disclosed;
  they are never silently counted or treated as zero.
- participants_affected counts unique participants; event_occurrences counts records.
- Reported sex is decoded only through the CDISC SEX codelist (F, M, U,
  UNDIFFERENTIATED). Other values are preserved as reported. Unknown or additional
  categories get their own rows and are never merged into Female/Male.
- Serious and non-serious events are separate rows, mirroring registry AE tables.
- Optional PK (PP domain) becomes per arm x sex geometric-mean PKRows. Optional ECG (EG
  domain, QTcF) is summarised per participant. Participant-level values are kept only
  in this process's memory (ParticipantTable) for allowlisted analyses; they are never
  copied into TrialBundle, run results or storage.
- CSV only: no pickle, executable content or arbitrary formats.
"""

import csv
import hashlib
import io
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from app.contracts import (
    AdverseEventRow,
    DataAvailability,
    DemographicRow,
    NarrativeEntry,
    PKRow,
    SourceLocator,
    SourceRecord,
    TrialBundle,
)

MAX_FILE_BYTES = 10 * 1024 * 1024
DM_REQUIRED = ("STUDYID", "USUBJID", "SEX", "ARMCD", "ARM", "RFXSTDTC")
AE_REQUIRED = ("STUDYID", "USUBJID", "AEDECOD", "AESER", "AESTDTC")
NOT_TREATED_ARMS = {"SCRNFAIL", "NOTASSGN", "NOTTRT"}
# CDISC Controlled Terminology, SEX codelist (C66731). A documented decode, not inference.
SEX_CODELIST = {
    "F": "Female",
    "M": "Male",
    "U": "Unknown",
    "UNDIFFERENTIATED": "Undifferentiated",
}
SERIOUSNESS = {"Y": "serious", "N": "non_serious"}
POPULATION = "Safety population (participants with a recorded first dose)"
WINDOW = "Treatment-emergent: onset on or after first-dose date"
MAX_LOCATOR_LINES = 40
PP_REQUIRED = ("STUDYID", "USUBJID", "PPTESTCD", "PPSTRESN", "PPSTRESU")
EG_REQUIRED = ("STUDYID", "USUBJID", "EGTESTCD", "EGSTRESN", "EGBLFL")
# Exposure parameters summarised as geometric means (log-normal by convention).
EXPOSURE_PARAMETERS = ("AUCIFO", "AUCINF", "AUCLST", "AUCTAU", "CMAX")
QTC_TESTCD = "QTCF"


@dataclass
class ParticipantTable:
    """Participant-level values for allowlisted analyses. In-memory only, never serialised."""

    study_id: str
    is_synthetic: bool
    source_ids: dict[str, str]  # domain -> source_id
    participants: dict[str, dict]  # USUBJID -> sex, armcd, arm, placebo
    teae: dict[str, set[str]] = field(default_factory=dict)  # AEDECOD -> USUBJIDs
    exposures: dict[str, dict[str, float]] = field(default_factory=dict)  # PPTESTCD -> values
    exposure_units: dict[str, str] = field(default_factory=dict)
    ecg: dict[str, dict] = field(default_factory=dict)  # USUBJID -> baseline/max values


_TABLES: dict[str, ParticipantTable] = {}


def _table_key(sources) -> str | None:
    parts = sorted(
        f"{s.source_id}:{s.content_hash}" for s in sources if s.source_id.startswith("participant-")
    )
    return hashlib.sha256("|".join(parts).encode()).hexdigest() if parts else None


def participant_table_for(bundle: TrialBundle) -> ParticipantTable | None:
    """Return participant-level data loaded in this process for exactly these sources."""
    key = _table_key(bundle.sources)
    table = _TABLES.get(key) if key else None
    return table if table is not None and table.study_id == bundle.trial_id else None


class ParticipantDataError(ValueError):
    """The supplied files cannot be loaded safely; message is safe to display."""


@dataclass(frozen=True)
class _Table:
    rows: list[tuple[int, dict[str, str]]]  # (1-based CSV line number, row)
    source: SourceRecord
    name: str


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-") or "blank"


def _read_csv(path: Path, required, source_id, *, is_synthetic, retrieved_at) -> _Table:
    path = Path(path)
    if path.suffix.casefold() != ".csv":
        raise ParticipantDataError(f"{path.name}: only .csv files are accepted")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ParticipantDataError(f"{path.name}: exceeds {MAX_FILE_BYTES} byte limit")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParticipantDataError(f"{path.name}: must be UTF-8 encoded") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in required if c not in header]
    if missing:
        raise ParticipantDataError(f"{path.name}: missing required columns {missing}")
    reader.fieldnames = header
    rows = []
    for row in reader:
        if None in row:
            raise ParticipantDataError(f"{path.name}: line {reader.line_num} has extra fields")
        rows.append((reader.line_num, {k: (v or "").strip() for k, v in row.items()}))
    source = SourceRecord(
        source_id=source_id,
        source_type="synthetic" if is_synthetic else "uploaded_data",
        title=f"Participant-level {path.stem.upper()} domain ({path.name})",
        retrieved_at=retrieved_at,
        content_hash=hashlib.sha256(raw).hexdigest(),
        licence_status="unknown",
        access_level="uploaded",
        is_synthetic=is_synthetic,
    )
    return _Table(rows=rows, source=source, name=path.name)


def _parse_date(value: str) -> date | None:
    """Full ISO 8601 dates only; partial SDTM dates (e.g. 2025-03) are undeterminable."""
    if len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _decode_sex(value: str) -> str:
    if not value:
        return "Not reported"
    return SEX_CODELIST.get(value.upper(), value)


def _lines(lines: list[int]) -> str:
    shown = ",".join(str(n) for n in lines[:MAX_LOCATOR_LINES])
    more = f" (+{len(lines) - MAX_LOCATOR_LINES} more)" if len(lines) > MAX_LOCATOR_LINES else ""
    return f"{shown}{more}" if lines else "none"


def load_participant_dataset(
    dm_path: Path,
    ae_path: Path,
    *,
    is_synthetic: bool,
    title: str | None = None,
    narratives_path: Path | None = None,
    pp_path: Path | None = None,
    eg_path: Path | None = None,
) -> TrialBundle:
    """Load DM and AE CSV files into a validated, source-linked TrialBundle.

    Verbatim AETERM text from safety-population records (and optional free-text
    narratives with a TEXT column) become narrative entries for interpretation only.
    They never change counts, which are derived from AEDECOD and dates.
    """
    retrieved_at = datetime.now(UTC)
    narratives: list[NarrativeEntry] = []
    dm = _read_csv(
        dm_path,
        DM_REQUIRED,
        "participant-dm",
        is_synthetic=is_synthetic,
        retrieved_at=retrieved_at,
    )
    ae = _read_csv(
        ae_path,
        AE_REQUIRED,
        "participant-ae",
        is_synthetic=is_synthetic,
        retrieved_at=retrieved_at,
    )
    studies = {r["STUDYID"] for _, r in dm.rows} | {r["STUDYID"] for _, r in ae.rows}
    if len(studies) != 1 or "" in studies:
        raise ParticipantDataError("DM and AE must contain exactly one shared, non-empty STUDYID")
    study_id = studies.pop()

    # --- Participants and safety population -------------------------------------------
    # Safety analyses use the arm actually received (ACTARMCD) when supplied.
    participants: dict[str, dict] = {}
    excluded_participants = 0
    for line, row in dm.rows:
        sid = row["USUBJID"]
        if not sid:
            raise ParticipantDataError(f"{dm.name}: line {line} has no USUBJID")
        if sid in participants:
            raise ParticipantDataError(f"{dm.name}: duplicate USUBJID {sid}")
        first_dose = _parse_date(row["RFXSTDTC"])
        actual = row.get("ACTARMCD", "")
        armcd = actual or row["ARMCD"]
        arm = (row.get("ACTARM", "") if actual else row["ARM"]) or armcd
        treated = bool(armcd) and armcd.upper() not in NOT_TREATED_ARMS and first_dose is not None
        participants[sid] = {
            "line": line,
            "sex_raw": row["SEX"],
            "sex": _decode_sex(row["SEX"]),
            "armcd": armcd,
            "arm": arm,
            "first_dose": first_dose,
            "treated": treated,
        }
        if not treated:
            excluded_participants += 1
    safety = {sid: p for sid, p in participants.items() if p["treated"]}
    if not safety:
        raise ParticipantDataError("No treated participants with a first-dose date in DM")

    arms: dict[str, str] = {}
    at_risk: dict[tuple[str, str], list[int]] = {}
    for p in safety.values():
        arms.setdefault(p["armcd"], p["arm"])
        at_risk.setdefault((p["armcd"], p["sex"]), []).append(p["line"])
    arm_totals = {
        armcd: sum(len(v) for (a, _), v in at_risk.items() if a == armcd) for armcd in arms
    }

    demographic_rows = []
    for (armcd, sex), lines in sorted(at_risk.items()):
        raw_codes = sorted(
            {
                safety_p["sex_raw"]
                for safety_p in safety.values()
                if safety_p["armcd"] == armcd and safety_p["sex"] == sex
            }
        )
        demographic_rows.append(
            DemographicRow(
                row_id=f"dm-{_slug(armcd)}-{_slug(sex)}",
                category="Sex",
                reported_label=sex,
                group_id=armcd,
                analysis_population=POPULATION,
                count=len(lines),
                denominator=arm_totals[armcd],
                source_locator=SourceLocator(
                    source_id=dm.source.source_id,
                    location=f"{dm.name} lines {_lines(lines)}",
                    excerpt=f"SEX as reported: {', '.join(repr(c) for c in raw_codes)}; "
                    f"ARMCD={armcd}",
                ),
                is_synthetic=is_synthetic,
            )
        )

    # --- Adverse events -----------------------------------------------------------------
    excluded = {"pre_existing": 0, "unknown_onset": 0, "not_in_safety_population": 0, "no_term": 0}
    unspecified_seriousness = 0
    # (term, seriousness, armcd, sex) -> {"subjects": set, "lines": list}
    cells: dict[tuple[str, str, str, str], dict] = {}
    terms: set[tuple[str, str]] = set()
    teae_subjects: dict[str, set[str]] = {}
    for line, row in ae.rows:
        p = safety.get(row["USUBJID"])
        if p is None:
            excluded["not_in_safety_population"] += 1
            continue
        if row.get("AETERM"):
            narratives.append(
                NarrativeEntry(
                    entry_id=f"aeterm-line-{line}",
                    text=row["AETERM"][:20000],
                    locator=SourceLocator(
                        source_id=ae.source.source_id, location=f"{ae.name} line {line} AETERM"
                    ),
                )
            )
        term = row["AEDECOD"] or row.get("AETERM", "")
        if not term:
            excluded["no_term"] += 1
            continue
        onset = _parse_date(row["AESTDTC"])
        if onset is None:
            excluded["unknown_onset"] += 1
            continue
        if onset < p["first_dose"]:
            excluded["pre_existing"] += 1
            continue
        teae_subjects.setdefault(term, set()).add(row["USUBJID"])
        seriousness = SERIOUSNESS.get(row["AESER"].upper(), "unspecified")
        if seriousness == "unspecified":
            unspecified_seriousness += 1
        terms.add((term, seriousness))
        cell = cells.setdefault(
            (term, seriousness, p["armcd"], p["sex"]), {"subjects": set(), "lines": []}
        )
        cell["subjects"].add(row["USUBJID"])
        cell["lines"].append(line)

    adverse_event_rows = []
    for term, seriousness in sorted(terms):
        for (armcd, sex), dm_lines in sorted(at_risk.items()):
            cell = cells.get((term, seriousness, armcd, sex), {"subjects": set(), "lines": []})
            affected, records = len(cell["subjects"]), len(cell["lines"])
            adverse_event_rows.append(
                AdverseEventRow(
                    row_id=f"ae-{_slug(armcd)}-{_slug(term)}-{seriousness}-{_slug(sex)}",
                    source_term=term,
                    group_id=armcd,
                    intervention=arms[armcd],
                    reported_sex_category=sex,
                    analysis_population=POPULATION,
                    participants_affected=affected,
                    participants_at_risk=len(dm_lines),
                    event_occurrences=records,
                    event_seriousness=seriousness,
                    reporting_window=WINDOW,
                    source_locator=SourceLocator(
                        source_id=ae.source.source_id,
                        location=f"{ae.name} lines {_lines(cell['lines'])}; "
                        f"denominator {dm.name} ARMCD={armcd}, SEX={sex}",
                        excerpt=f"AEDECOD '{term}': {affected} of {len(dm_lines)} treated "
                        f"participants, {records} records",
                    ),
                    is_synthetic=is_synthetic,
                )
            )

    sexes = {sex for (_, sex) in at_risk}
    limitations = [
        "Participant-level counts derived deterministically from supplied DM/AE files.",
        "Zero counts assume complete AE capture: no record for a treated participant is "
        "counted as not affected.",
        "Treatment-emergent rule: onset on or after the first-dose date; same-day onset "
        "counts as treatment-emergent.",
        "AEDECOD terms are used as reported; their terminology/version is not verified "
        "and no codes are generated.",
        "Severity and relatedness columns are preserved in the source file but are not "
        "carried by contract v1.0 rows.",
        f"Excluded AE records: {excluded['pre_existing']} pre-existing (onset before first "
        f"dose), {excluded['unknown_onset']} with missing/partial onset date, "
        f"{excluded['not_in_safety_population']} not in the safety population, "
        f"{excluded['no_term']} without a term. Excluded records are not treated as zero.",
        f"{excluded_participants} DM participants excluded (screen failure, not treated or "
        "no first-dose date).",
    ]
    if unspecified_seriousness:
        limitations.append(
            f"{unspecified_seriousness} AE records lack Y/N seriousness; those rows cannot be "
            "compared."
        )
    other = sorted(sexes - {"Female", "Male"})
    if other:
        limitations.append(
            f"Additional reported sex categories {other} are retained descriptively and not "
            "merged into Female/Male comparisons."
        )
    if is_synthetic:
        limitations.insert(0, "SYNTHETIC DATA: no real participants, drug or trial results.")

    sources = [dm.source, ae.source]
    if narratives_path is not None:
        notes = _read_csv(
            narratives_path,
            ("TEXT",),
            "participant-narratives",
            is_synthetic=is_synthetic,
            retrieved_at=retrieved_at,
        )
        sources.append(notes.source)
        for line, row in notes.rows:
            if row["TEXT"]:
                narratives.append(
                    NarrativeEntry(
                        entry_id=f"narrative-line-{line}",
                        text=row["TEXT"][:20000],
                        locator=SourceLocator(
                            source_id=notes.source.source_id,
                            location=f"{notes.name} line {line} TEXT",
                        ),
                    )
                )
    if narratives:
        limitations.append(
            f"{len(narratives)} verbatim/narrative texts are supplied for interpretation "
            "only; they do not alter derived counts."
        )

    table = ParticipantTable(
        study_id=study_id,
        is_synthetic=is_synthetic,
        source_ids={"dm": dm.source.source_id, "ae": ae.source.source_id},
        participants={
            sid: {
                "sex": p["sex"],
                "armcd": p["armcd"],
                "arm": p["arm"],
                "placebo": "placebo" in p["arm"].casefold(),
            }
            for sid, p in safety.items()
        },
        teae=teae_subjects,
    )
    pk_rows: list[PKRow] = []
    availability_notes = []
    if pp_path is not None:
        pp = _read_csv(
            pp_path,
            PP_REQUIRED,
            "participant-pp",
            is_synthetic=is_synthetic,
            retrieved_at=retrieved_at,
        )
        _check_study(pp, study_id)
        sources.append(pp.source)
        table.source_ids["pp"] = pp.source.source_id
        pk_rows, pk_limitations = _load_pk(pp, safety, arms, table, is_synthetic)
        limitations.extend(pk_limitations)
    else:
        availability_notes.append("No PK domain supplied with the participant-level files.")
    if eg_path is not None:
        eg = _read_csv(
            eg_path,
            EG_REQUIRED,
            "participant-eg",
            is_synthetic=is_synthetic,
            retrieved_at=retrieved_at,
        )
        _check_study(eg, study_id)
        sources.append(eg.source)
        table.source_ids["eg"] = eg.source.source_id
        limitations.extend(_load_ecg(eg, safety, table))
    pk_sexes = {r.reported_sex_category for r in pk_rows}

    bundle = TrialBundle(
        trial_id=study_id,
        title=title or f"Participant-level dataset {study_id}",
        interventions=sorted(set(arms.values())),
        sources=sources,
        narrative_entries=narratives,
        demographic_rows=demographic_rows,
        adverse_event_rows=adverse_event_rows,
        pk_rows=pk_rows,
        availability=DataAvailability(
            representation="available",
            sex_stratified_ae="available" if {"Female", "Male"} <= sexes else "missing",
            sex_stratified_pk="available" if {"Female", "Male"} <= pk_sexes else "missing",
            participant_level="available",
            notes=availability_notes,
        ),
        limitations=limitations,
        is_synthetic=is_synthetic,
    )
    _TABLES[_table_key(bundle.sources)] = table
    return bundle


def _check_study(table: _Table, study_id: str) -> None:
    studies = {r["STUDYID"] for _, r in table.rows}
    if studies and studies != {study_id}:
        raise ParticipantDataError(f"{table.name}: STUDYID must match DM/AE ({study_id})")


def _positive_float(value: str) -> float | None:
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) and number > 0 else None


def _load_pk(pp: _Table, safety, arms, table: ParticipantTable, is_synthetic):
    excluded = {"not_in_safety_population": 0, "non_positive_or_missing": 0}
    lines: dict[tuple[str, str], dict[str, int]] = {}
    for line, row in pp.rows:
        code = row["PPTESTCD"].upper()
        if code not in EXPOSURE_PARAMETERS:
            continue
        sid = row["USUBJID"]
        if sid not in safety:
            excluded["not_in_safety_population"] += 1
            continue
        value = _positive_float(row["PPSTRESN"])
        if value is None:
            excluded["non_positive_or_missing"] += 1
            continue
        values = table.exposures.setdefault(code, {})
        if sid in values:
            raise ParticipantDataError(
                f"{pp.name}: line {line} repeats {code} for {sid}; supply one visit per file"
            )
        unit = row["PPSTRESU"]
        if table.exposure_units.setdefault(code, unit) != unit:
            raise ParticipantDataError(f"{pp.name}: {code} uses more than one unit")
        values[sid] = value
        lines.setdefault((code, sid), {})[sid] = line
    rows = []
    for code, values in sorted(table.exposures.items()):
        groups: dict[tuple[str, str], list[tuple[str, float]]] = {}
        for sid, value in values.items():
            p = safety[sid]
            groups.setdefault((p["armcd"], p["sex"]), []).append((sid, value))
        for (armcd, sex), members in sorted(groups.items()):
            logs = [math.log(v) for _, v in members]
            n = len(logs)
            mean = sum(logs) / n
            variability = None
            if n >= 2:
                sd = math.sqrt(sum((x - mean) ** 2 for x in logs) / (n - 1))
                variability = f"geometric CV {100 * math.sqrt(math.exp(sd**2) - 1):.1f}%"
            member_lines = sorted(lines[(code, sid)][sid] for sid, _ in members)
            rows.append(
                PKRow(
                    row_id=f"pk-{_slug(armcd)}-{_slug(code)}-{_slug(sex)}",
                    parameter=code,
                    value=round(math.exp(mean), 6),
                    unit=table.exposure_units[code],
                    summary_statistic="geometric mean",
                    reported_sex_category=sex,
                    group_id=armcd,
                    dose=arms[armcd],
                    sample_size=n,
                    variability=variability,
                    source_locator=SourceLocator(
                        source_id=pp.source.source_id,
                        location=f"{pp.name} lines {_lines(member_lines)}",
                        excerpt=f"{code} geometric mean of {n} participants",
                    ),
                    is_synthetic=is_synthetic,
                )
            )
    limitations = [
        "PK summaries are geometric means of participant-level values from one visit; "
        "Female/Male ratios are computed from participant-level values only.",
        f"Excluded PK records: {excluded['not_in_safety_population']} outside the safety "
        f"population, {excluded['non_positive_or_missing']} missing or non-positive.",
    ]
    return rows, limitations


def _load_ecg(eg: _Table, safety, table: ParticipantTable) -> list[str]:
    baseline: dict[str, list[float]] = {}
    post: dict[str, list[tuple[float, int]]] = {}
    excluded = 0
    for line, row in eg.rows:
        if row["EGTESTCD"].upper() != QTC_TESTCD:
            continue
        sid = row["USUBJID"]
        if sid not in safety:
            excluded += 1
            continue
        try:
            value = float(row["EGSTRESN"])
        except ValueError:
            excluded += 1
            continue
        if not math.isfinite(value) or value <= 0:
            excluded += 1
            continue
        if row["EGBLFL"].upper() == "Y":
            baseline.setdefault(sid, []).append(value)
        else:
            post.setdefault(sid, []).append((value, line))
    no_baseline = 0
    for sid, values in post.items():
        base = baseline.get(sid)
        if not base or len(base) != 1:
            no_baseline += 1
            continue
        peak = max(v for v, _ in values)
        table.ecg[sid] = {
            "baseline": base[0],
            "max_post": peak,
            "max_change": max(v - base[0] for v, _ in values),
            "lines": [ln for _, ln in values],
        }
    return [
        f"ECG ({QTC_TESTCD}): {len(table.ecg)} participants with one baseline and at least "
        f"one post-baseline value; {no_baseline} without a unique baseline and {excluded} "
        "records outside the safety population or non-numeric were excluded."
    ]
