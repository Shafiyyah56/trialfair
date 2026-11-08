"""Run-local progress snapshots for honest polling of active investigations."""

from datetime import UTC, datetime
from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import (
    AgentEvent,
    EvidenceReport,
    InvestigationReport,
    PlannerReport,
    RunResult,
    ScreeningOutput,
)

RunState = Literal["queued", "running", "completed", "partial", "failed"]
AgentName = Literal["interpreter", "safety", "evidence", "planner", "orchestrator"]


class RunAccepted(BaseModel):
    """Small response returned before agent execution finishes."""

    model_config = ConfigDict(extra="forbid")
    run_id: str
    status: Literal["queued"] = "queued"
    progress_url: str


class RunProgress(BaseModel):
    """Sanitized, validated state that may safely be shown while a run is active."""

    model_config = ConfigDict(extra="forbid")
    run_id: str
    status: RunState
    stage: str
    progress: float = Field(ge=0, le=1)
    active_agent: AgentName | None = None
    events: list[AgentEvent] = Field(default_factory=list)
    screening: ScreeningOutput | None = None
    evidence_reports: list[EvidenceReport] = Field(default_factory=list)
    investigation: InvestigationReport | None = None
    planner_report: PlannerReport | None = None
    result_available: bool = False
    started_at: datetime
    updated_at: datetime
    error: str | None = None


class ActiveRunRegistry:
    """Thread-safe in-memory state for one local API process.

    Final validated results remain in the configured RunStore. Active state is
    intentionally ephemeral: restarting the local API interrupts active work.
    """

    def __init__(self) -> None:
        self._runs: dict[str, RunProgress] = {}
        self._lock = Lock()

    def start(self, run_id: str, *, includes_interpretation: bool) -> RunProgress:
        now = datetime.now(UTC)
        stage = "Interpreting trial data" if includes_interpretation else "Preparing investigation"
        active_agent: AgentName = "interpreter" if includes_interpretation else "orchestrator"
        snapshot = RunProgress(
            run_id=run_id,
            status="queued",
            stage=stage,
            progress=0.05,
            active_agent=active_agent,
            started_at=now,
            updated_at=now,
        )
        with self._lock:
            self._runs[run_id] = snapshot
        return snapshot.model_copy(deep=True)

    def record_event(
        self,
        run_id: str,
        event: AgentEvent,
        evidence_reports: list[EvidenceReport],
        investigation: InvestigationReport | None = None,
        planner_report: PlannerReport | None = None,
    ) -> None:
        labels = {
            "interpreter": "Interpreting trial data",
            "safety": "Investigating safety findings",
            "evidence": "Researching external evidence",
            "planner": "Planning follow-up investigations",
            "orchestrator": "Validating and assembling results",
        }
        milestones = {
            "interpreter": 0.15,
            "safety": 0.5,
            "evidence": 0.7,
            "planner": 0.9,
            "orchestrator": 0.95,
        }
        with self._lock:
            current = self._runs[run_id]
            current.status = "running"
            current.active_agent = event.agent
            current.stage = labels[event.agent]
            current.progress = max(current.progress, milestones[event.agent])
            current.events.append(event.model_copy(deep=True))
            current.evidence_reports = [report.model_copy(deep=True) for report in evidence_reports]
            if investigation is not None:
                current.investigation = investigation.model_copy(deep=True)
            if planner_report is not None:
                current.planner_report = planner_report.model_copy(deep=True)
            current.updated_at = datetime.now(UTC)

    def screening_ready(self, run_id: str, screening: ScreeningOutput) -> None:
        with self._lock:
            current = self._runs[run_id]
            current.status = "running"
            current.stage = "Investigating safety findings"
            current.active_agent = "safety"
            current.progress = max(current.progress, 0.4)
            current.screening = screening.model_copy(deep=True)
            current.updated_at = datetime.now(UTC)

    def finish(self, result: RunResult) -> None:
        with self._lock:
            current = self._runs[result.run_id]
            current.status = result.status
            current.stage = (
                "Report ready" if result.status == "completed" else "Partial report ready"
            )
            current.progress = 1.0
            current.active_agent = None
            current.events = [event.model_copy(deep=True) for event in result.events]
            current.screening = result.screening.model_copy(deep=True) if result.screening else None
            current.evidence_reports = [
                report.model_copy(deep=True) for report in result.evidence_reports
            ]
            current.investigation = (
                result.investigation.model_copy(deep=True) if result.investigation else None
            )
            current.planner_report = (
                result.planner_report.model_copy(deep=True) if result.planner_report else None
            )
            current.result_available = True
            current.updated_at = datetime.now(UTC)
            current.error = "; ".join(result.errors) or None

    def fail(self, run_id: str, message: str) -> None:
        with self._lock:
            current = self._runs[run_id]
            current.status = "failed"
            current.stage = "Investigation stopped"
            current.active_agent = None
            current.updated_at = datetime.now(UTC)
            current.error = message

    def get(self, run_id: str) -> RunProgress | None:
        with self._lock:
            current = self._runs.get(run_id)
            return current.model_copy(deep=True) if current else None
