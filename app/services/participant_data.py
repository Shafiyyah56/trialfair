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
- CSV only: no pickle, executable content or arbitrary formats.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from app.contracts import (
    AdverseEventRow,
    DataAvailability,
    DemographicRow,
    NarrativeEntry,
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

    return TrialBundle(
        trial_id=study_id,
        title=title or f"Participant-level dataset {study_id}",
        interventions=sorted(set(arms.values())),
        sources=sources,
        narrative_entries=narratives,
        demographic_rows=demographic_rows,
        adverse_event_rows=adverse_event_rows,
        availability=DataAvailability(
            representation="available",
            sex_stratified_ae="available" if {"Female", "Male"} <= sexes else "missing",
            sex_stratified_pk="missing",
            participant_level="available",
            notes=["No PK domain supplied with the participant-level files."],
        ),
        limitations=limitations,
        is_synthetic=is_synthetic,
    )
