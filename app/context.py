"""In-process dependency injection and one bounded budget shared by every agent."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from typing import Literal

from app.config import Settings
from app.contracts import (
    AgentEvent,
    AnalysisRequest,
    AnalysisResult,
    EvidenceReport,
    EvidenceRequest,
    TrialBundle,
)
from app.model_client import ModelClient
from app.services.clinical_trials import ClinicalTrialsService
from app.services.europe_pmc import EuropePMCService
from app.services.terminology import TerminologyService

BudgetKind = Literal["model_turn", "external_request", "evidence_request", "additional_analysis"]
AnalysisHandler = Callable[[AnalysisRequest, "ToolContext"], Awaitable[AnalysisResult]]
EvidenceHandler = Callable[[EvidenceRequest, "ToolContext"], Awaitable[EvidenceReport]]
EventSink = Callable[[AgentEvent], None]


class BudgetExceeded(RuntimeError):
    """Catch at orchestration boundaries and preserve verified partial results."""


@dataclass
class RunBudget:
    """Atomic counters prevent nested/concurrent agents from resetting limits."""

    deadline: float
    limits: dict[BudgetKind, int]
    used: dict[BudgetKind, int] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> "RunBudget":
        return cls(
            deadline=monotonic() + settings.run_timeout_seconds,
            limits={
                "model_turn": settings.max_model_turns,
                "external_request": settings.max_external_requests,
                "evidence_request": settings.max_evidence_requests,
                "additional_analysis": settings.max_additional_analyses,
            },
        )

    def remaining_seconds(self) -> float:
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise BudgetExceeded("Run deadline exhausted")
        return remaining

    def consume(self, kind: BudgetKind) -> None:
        """Call immediately before each actual attempt, including retries."""
        with self._lock:
            self.remaining_seconds()
            if kind not in self.limits:
                raise ValueError(f"Unknown budget kind: {kind}")
            if self.used.get(kind, 0) >= self.limits[kind]:
                raise BudgetExceeded(f"Run budget exhausted: {kind}")
            self.used[kind] = self.used.get(kind, 0) + 1


@dataclass
class ToolContext:
    """Create once per run. Never recreate the budget in a nested tool call.

    Service adapters consume external_request; the model adapter/caller consumes
    model_turn exactly once per provider attempt. The orchestrator dispatcher
    consumes evidence_request/additional_analysis and appends accepted results.
    Initial deterministic screening does not consume additional_analysis.
    Dataset references are registered in memory by the interpreter and must not
    be interpreted as arbitrary filesystem paths.
    """

    run_id: str
    settings: Settings
    model: ModelClient
    registry: ClinicalTrialsService
    literature: EuropePMCService
    terminology: TerminologyService
    budget: RunBudget
    emit: EventSink
    analysis_handler: AnalysisHandler
    evidence_handler: EvidenceHandler
    datasets: dict[str, TrialBundle] = field(default_factory=dict)
    additional_analyses: list[AnalysisResult] = field(default_factory=list)
    evidence_reports: list[EvidenceReport] = field(default_factory=list)
