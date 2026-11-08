"""Runtime composition: Agent 3 literature is wired; Agent 1 registry/terminology are pending.

Missing adapters fail visibly rather than returning synthetic or fabricated data.
The standalone screening endpoint can still run Agent 2 with the shared live model
while unavailable registry or external sources yield a partial investigation.
"""

from dataclasses import dataclass

from app.agents.evidence import run_evidence
from app.config import Settings
from app.context import RunBudget, ToolContext
from app.model_client import GeminiModelClient
from app.services.clinical_trials import ClinicalTrialsService
from app.services.europe_pmc import EuropePMCClient, EuropePMCService
from app.services.statistics import execute_analysis
from app.services.terminology import TerminologyService


class RuntimeNotReady(ValueError):
    """An actionable configuration problem, safe to display without provider secrets."""


class MissingService:
    """Explicit service placeholder until the owning branch provides an adapter."""

    is_available = False

    def __getattr__(self, name):
        async def unavailable(*args, **kwargs):
            raise NotImplementedError("Required source adapter is not yet wired")

        return unavailable


@dataclass
class RuntimeServices:
    registry: ClinicalTrialsService
    literature: EuropePMCService
    terminology: TerminologyService


def build_context(
    run_id: str,
    mode: str,
    *,
    services: RuntimeServices | None = None,
    settings: Settings | None = None,
) -> ToolContext:
    """Make one live model and cumulative budget per run; tests inject other factories."""
    settings = settings or Settings()
    if mode != "live":
        raise RuntimeNotReady(
            "No captured replay execution is configured. Load a saved run instead."
        )
    if settings.mode != "live":
        raise RuntimeNotReady("Server is not configured for live execution.")
    try:
        settings.require_live_credentials()
    except ValueError as exc:
        raise RuntimeNotReady("Configure GEMINI_API_KEY and GEMINI_MODEL in local .env.") from exc
    missing = MissingService()
    budget = RunBudget.from_settings(settings)
    services = services or RuntimeServices(
        missing,
        EuropePMCClient(budget, cache_dir=settings.data_dir / "cache" / "europe_pmc"),
        missing,
    )
    return ToolContext(
        run_id=run_id,
        settings=settings,
        model=GeminiModelClient(
            api_key=settings.gemini_api_key.get_secret_value(),
            model_id=settings.gemini_model,
        ),
        registry=services.registry,
        literature=services.literature,
        terminology=services.terminology,
        budget=budget,
        emit=lambda event: None,
        analysis_handler=execute_analysis,
        evidence_handler=run_evidence,
    )
