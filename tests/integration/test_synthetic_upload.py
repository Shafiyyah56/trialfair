"""Synthetic CSV upload through real loading/statistics, curated citations and planning."""

import base64
import io
import time
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.contracts import FindingAssessment, InvestigationReport, RunResult
from app.demo import run_curated_evidence
from app.model_client import ModelResponse, ToolCall
from app.services.statistics import execute_analysis
from app.storage import SQLiteRunStore
from app.synthetic_upload import (
    CSV_NAMES,
    PROFILE_LABELS,
    SyntheticUpload,
    load_upload,
    sample_bundle,
    upload_preview,
)

ROOT = Path(__file__).resolve().parents[2]


def payload(profile):
    directory = ROOT / "fixtures/synthetic" / profile / "data"
    return {
        "profile": profile,
        "is_synthetic": True,
        "files": [
            {
                "name": name,
                "data_base64": base64.b64encode((directory / name).read_bytes()).decode(),
            }
            for name in CSV_NAMES
            if (directory / name).exists()
        ],
    }


@pytest.mark.parametrize("profile", PROFILE_LABELS)
def test_preview_loads_real_csv_values_without_model_or_network(profile):
    def forbidden(*args):
        pytest.fail("Validation must not construct a model runtime")

    with TestClient(create_app(context_factory=forbidden)) as client:
        response = client.post("/synthetic/preview", json=payload(profile))
    assert response.status_code == 200
    preview = response.json()
    assert preview["trial_id"].startswith(f"SYN-{profile[3:]}")
    assert preview["is_synthetic"] and preview["safety_population"] > 80
    assert preview["pk_available"]
    assert preview["ecg_available"] == (profile == "syn722")
    assert sum(preview["reported_sex_counts"].values()) == preview["safety_population"]
    with ZipFile(io.BytesIO(sample_bundle(profile))) as archive:
        assert set(archive.namelist()) == set(preview["files"])
        assert "truth.json" not in archive.namelist()


@pytest.mark.parametrize(
    "mutation", ["missing-ae", "duplicate", "path", "encoding", "wrong-profile", "real"]
)
def test_invalid_uploads_rejected_before_model_construction(mutation):
    data = payload("syn401")
    if mutation == "missing-ae":
        data["files"] = [file for file in data["files"] if file["name"] != "ae.csv"]
    elif mutation == "duplicate":
        data["files"][1] = data["files"][0]
    elif mutation == "path":
        data["files"][0]["name"] = "../dm.csv"
    elif mutation == "encoding":
        data["files"][0]["data_base64"] = "not-base64"
    elif mutation == "wrong-profile":
        data["profile"] = "syn722"
    else:
        data["is_synthetic"] = False

    def forbidden(*args):
        pytest.fail("Invalid uploads must not construct a model runtime")

    with TestClient(create_app(context_factory=forbidden)) as client:
        assert client.post("/synthetic/runs/async", json=data).status_code == 422


class UploadModel:
    """Scripted decisions only; normal tests make no provider calls."""

    model_id = "synthetic-upload-test-not-live"

    def __init__(self):
        self.safety_inspected = False

    async def generate(self, messages, **kwargs):
        user = messages[-1].content
        properties = (kwargs.get("output_schema") or {}).get("properties", {})
        if "judgements" in properties:
            return ModelResponse(
                structured_output={
                    "judgements": [
                        {
                            "entry_id": e["entry_id"],
                            "assertion": "present",
                            "temporality": "unknown",
                            "needs_review": False,
                            "explanation": "Offline interpretation fixture",
                        }
                        for e in user["entries"]
                    ]
                }
            )
        if isinstance(user, dict) and "candidates" in user:
            self.candidates = user["candidates"][:2]
            ids = sorted({fid for c in self.candidates for fid in c["finding_ids"]})
            return ModelResponse(
                tool_calls=[
                    ToolCall(
                        call_id=f"plan-{i}", name="inspect_finding", arguments={"identifier": fid}
                    )
                    for i, fid in enumerate(ids)
                ]
            )
        if "choices" in properties:
            return ModelResponse(
                structured_output={
                    "choices": [
                        {
                            "recommendation_id": c["recommendation_id"],
                            "priority": "medium",
                            "reason": "follow_up",
                        }
                        for c in self.candidates
                    ]
                }
            )
        if "trial_id" in properties:
            return ModelResponse(
                structured_output=InvestigationReport(
                    trial_id=self.overview["trial_id"],
                    status="partial",
                    assessed_findings=[
                        FindingAssessment(
                            finding_id=f["finding_id"],
                            conclusion=f["description"],
                            priority=f["priority"],
                            rationale="Offline test review",
                            analysis_ids=f["analysis_ids"],
                        )
                        for f in self.overview["findings"][:3]
                    ],
                ).model_dump(mode="json")
            )
        if isinstance(user, dict) and "findings" in user and not self.safety_inspected:
            self.overview = user
            self.safety_inspected = True
            assert len(user["available_evidence_reports"][0]["evidence_items"]) == 2
            return ModelResponse(
                tool_calls=[
                    ToolCall(
                        call_id="safety",
                        name="inspect_finding",
                        arguments={"finding_id": user["findings"][0]["finding_id"]},
                    )
                ]
            )
        return ModelResponse(text="Inspection complete")


@pytest.mark.parametrize("profile", PROFILE_LABELS)
def test_upload_runs_all_four_agents_and_persists_aggregates(
    profile,
    context_factory,
    tmp_path,
):
    contexts = []

    def factory(run_id, mode):
        context, _ = context_factory()
        context.run_id = run_id
        context.settings = context.settings.model_copy(update={"mode": "live"})
        context.model = UploadModel()
        context.datasets = {}
        context.analysis_handler = execute_analysis
        contexts.append(context)
        return context

    with TestClient(
        create_app(context_factory=factory, store=SQLiteRunStore(tmp_path / "runs.sqlite"))
    ) as client:
        accepted = client.post("/synthetic/runs/async", json=payload(profile))
        assert accepted.status_code == 202
        for _ in range(100):
            progress = client.get(accepted.json()["progress_url"]).json()
            if progress["result_available"] or progress["status"] == "failed":
                break
            time.sleep(0.01)
        assert progress["result_available"], progress.get("error")
        result = RunResult.model_validate(client.get(f"/runs/{accepted.json()['run_id']}").json())
    assert result.screening.trial_bundle.is_synthetic
    assert result.planner_report.is_synthetic
    assert result.planner_report.recommendations
    assert len(result.evidence_reports[0].evidence_items) == 2
    assert all(not source.is_synthetic for source in result.evidence_reports[0].sources)
    assert {event.agent for event in result.events} >= {
        "interpreter",
        "safety",
        "evidence",
        "planner",
    }
    assert any(
        "compare_adverse" in a.method.lower() or "fisher" in a.method.lower()
        for a in result.screening.analyses
    )
    assert not result.screening.trial_bundle.narrative_entries  # Raw uploads not persisted.
    assert contexts[0]._closed


def test_class_profile_does_not_return_remdesivir_evidence(context_factory):
    import asyncio

    from app.contracts import EvidenceRequest

    context, _ = context_factory()
    context.demo_profile = "syn722"
    result = asyncio.run(
        run_curated_evidence(
            EvidenceRequest(
                request_id="class-check",
                trial_id="SYN-722-201",
                finding_ids=["test-finding"],
                question="Inspect class-context sources",
            ),
            context,
        )
    )
    assert len(result.evidence_items) == 2
    assert all("remdesivir" not in source.title.lower() for source in result.sources)


def test_preview_and_bundle_remain_synthetic():
    data = SyntheticUpload.model_validate(payload("syn401"))
    bundle = load_upload(data)
    assert upload_preview(data, bundle)["is_synthetic"]
    assert all(source.is_synthetic for source in bundle.sources)


def test_uploaded_values_are_used_instead_of_a_preset_result():
    data = payload("syn401")
    original = load_upload(SyntheticUpload.model_validate(data))
    import csv

    file = next(file for file in data["files"] if file["name"] == "ae.csv")
    reader = csv.DictReader(io.StringIO(base64.b64decode(file["data_base64"]).decode()))
    rows = list(reader)
    for row in rows:
        row["AEDECOD"] = "Uploaded marker symptom"
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=reader.fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    file["data_base64"] = base64.b64encode(buffer.getvalue().encode()).decode()
    changed = load_upload(SyntheticUpload.model_validate(data))
    assert changed.adverse_event_rows
    assert all(row.source_term == "Uploaded marker symptom" for row in changed.adverse_event_rows)
    before = next(s.content_hash for s in original.sources if s.source_id == "participant-ae")
    after = next(s.content_hash for s in changed.sources if s.source_id == "participant-ae")
    assert before != after


def test_upload_form_renders_and_requires_synthetic_confirmation():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "app/ui/dashboard.py"), default_timeout=10).run()
    assert not app.exception
    assert app.radio[0].value == "Synthetic CSV upload"
    assert app.selectbox[0].value == "syn401"
    validate = next(
        button for button in app.button if button.label == "Validate files without running AI"
    )
    validate.click().run()
    assert not app.exception
    assert any("Confirm these are simulated" in error.value for error in app.error)
