"""Compose Agents 1–3 with run-scoped sources, model, budget and resource ownership."""

from dataclasses import dataclass

import httpx

from app.agents.evidence import run_evidence
from app.agents.planner import run_planner
from app.config import Settings
from app.context import RunBudget, ToolContext
from app.model_client import GeminiModelClient
from app.services.clinical_trials import ClinicalTrialsClient, ClinicalTrialsService
from app.services.europe_pmc import EuropePMCClient, EuropePMCService
from app.services.statistics import execute_analysis
from app.services.terminology import SuppliedTerminology, TerminologyService


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
    budget = RunBudget.from_settings(settings)
    model = GeminiModelClient(
        api_key=settings.gemini_api_key.get_secret_value(),
        model_id=settings.gemini_model,
    )
    resources = []
    if services is None:
        http_client = httpx.AsyncClient()
        resources.append(http_client.aclose)
        services = RuntimeServices(
            ClinicalTrialsClient(
                http_client, budget, cache_dir=settings.data_dir / "cache" / "clinical_trials"
            ),
            EuropePMCClient(
                budget,
                cache_dir=settings.data_dir / "cache" / "europe_pmc",
                http_client=http_client,
            ),
            SuppliedTerminology(),
        )
    return ToolContext(
        run_id=run_id,
        settings=settings,
        model=model,
        registry=services.registry,
        literature=services.literature,
        terminology=services.terminology,
        budget=budget,
        emit=lambda event: None,
        analysis_handler=execute_analysis,
        evidence_handler=run_evidence,
        planner_handler=run_planner,
        resource_closers=resources,
    )
