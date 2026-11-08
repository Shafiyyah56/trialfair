"""Synthetic-only CSV uploads, validated through Agent 1's existing SDTM loader."""

import base64
import io
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import Field, model_validator

from app.contracts import Contract, TrialInput
from app.services.participant_data import load_participant_dataset, participant_table_for
from app.validation import validate_screening

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
CSV_NAMES = ("dm.csv", "ae.csv", "pp.csv", "eg.csv", "narratives.csv")
PROFILE_LABELS = {
    "syn401": "SYN-401 · hypnotic class",
    "syn722": "SYN-722 · cardiac repolarization class",
    "syn318": "SYN-318 · antiseizure class",
}
PROFILE_PREFIXES = {key: f"SYN-{key[3:]}-" for key in PROFILE_LABELS}
ROOT = Path(__file__).resolve().parents[1]


class UploadedCSV(Contract):
    name: Literal["dm.csv", "ae.csv", "pp.csv", "eg.csv", "narratives.csv"]
    data_base64: str = Field(min_length=1, max_length=4 * ((MAX_UPLOAD_BYTES + 2) // 3))


class SyntheticUpload(Contract):
    profile: Literal["syn401", "syn722", "syn318"]
    is_synthetic: Literal[True]
    files: list[UploadedCSV] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def require_domains(self):
        names = [file.name for file in self.files]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate CSV domain names are not accepted")
        if not {"dm.csv", "ae.csv"} <= set(names):
            raise ValueError("Upload both dm.csv and ae.csv")
        return self


def load_upload(payload: SyntheticUpload):
    """Preserve exact file bytes/hash; temporary files are removed after validation."""
    from app.contracts import ScreeningOutput

    with TemporaryDirectory(prefix="trialfair-synthetic-") as temporary:
        directory = Path(temporary)
        for file in payload.files:
            try:
                raw = base64.b64decode(file.data_base64, validate=True)
            except ValueError as exc:
                raise ValueError(f"{file.name}: invalid upload encoding") from exc
            if len(raw) > MAX_UPLOAD_BYTES:
                raise ValueError(f"{file.name}: exceeds the 2 MB upload limit")
            # Names are an enum, never a user-supplied filesystem path.
            (directory / file.name).write_bytes(raw)
        optional = {name: directory / name for name in CSV_NAMES if (directory / name).exists()}
        bundle = load_participant_dataset(
            directory / "dm.csv",
            directory / "ae.csv",
            is_synthetic=True,
            narratives_path=optional.get("narratives.csv"),
            pp_path=optional.get("pp.csv"),
            eg_path=optional.get("eg.csv"),
        )
    if not bundle.trial_id.startswith(PROFILE_PREFIXES[payload.profile]):
        raise ValueError("The STUDYID does not match the selected class evidence profile")
    bundle.title = f"Uploaded synthetic participant trial {bundle.trial_id}"
    validate_screening(ScreeningOutput(trial_bundle=bundle))
    return bundle


def upload_preview(payload: SyntheticUpload, bundle=None):
    bundle = bundle or load_upload(payload)
    table = participant_table_for(bundle)
    return {
        "trial_id": bundle.trial_id,
        "is_synthetic": True,
        "safety_population": len(table.participants) if table else 0,
        "reported_sex_counts": dict(Counter(p["sex"] for p in table.participants.values()))
        if table
        else {},
        "files": [file.name for file in payload.files],
        "arms": bundle.interventions,
        "pk_available": bool(table and table.exposures),
        "ecg_available": bool(table and table.ecg),
        "curated_profile": PROFILE_LABELS[payload.profile],
        "source_count": 2,
        "limitations": bundle.limitations,
        "note": "Simulated observations. Class-context papers do not validate the fictional drug.",
    }


def register_upload(context, payload: SyntheticUpload, bundle) -> TrialInput:
    from app.agents.planner import run_planner
    from app.demo import run_curated_evidence

    context.demo_profile = payload.profile
    context.evidence_handler = run_curated_evidence
    context.planner_handler = context.planner_handler or run_planner
    reference = f"uploaded-{uuid4().hex}"
    context.datasets[reference] = bundle
    return TrialInput(dataset_refs=[reference], mode="live")


def sample_bundle(profile: str) -> bytes:
    """Download CSVs only; truth/evaluation/generating code never enter model input."""
    if profile not in PROFILE_LABELS:
        raise ValueError("Unknown sample dataset")
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        directory = ROOT / "fixtures/synthetic" / profile / "data"
        for name in CSV_NAMES:
            path = directory / name
            if path.exists():
                archive.writestr(name, path.read_bytes())
    return buffer.getvalue()
