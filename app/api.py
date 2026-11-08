"""Local research API with injected runtimes and validated persisted results.

The default runtime has Agent 2 and Europe PMC-backed Agent 3. Missing upstream
components never become fake live results. Bind to localhost for the hackathon;
there is no account or public-hosting security layer in this MVP.
"""

from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from app.config import Settings
from app.context import ToolContext
from app.contracts import Contract, HealthResponse, RunResult, ScreeningOutput, TrialInput
from app.orchestrator import investigate_screening, run_trial
from app.runtime import RuntimeNotReady, build_context
from app.storage import RunStore, SQLiteRunStore


class InvestigationInput(Contract):
    """Agent 2 can run independently on an Agent 1 ScreeningOutput JSON payload."""

    screening: ScreeningOutput
    mode: Literal["live", "replay"] = "live"


ContextFactory = Callable[[str, str], ToolContext]


def create_app(
    *,
    context_factory: ContextFactory | None = None,
    store: RunStore | None = None,
) -> FastAPI:
    """Dependency injection enables integration tests and future real source adapters."""
    application = FastAPI(title="TrialFair", version="0.2.0")

    def run_store():
        return store if store is not None else SQLiteRunStore(Settings().data_dir / "runs.sqlite")

    async def execute(payload):
        factory = context_factory or build_context
        try:
            context = factory(str(uuid4()), payload.mode)
        except RuntimeNotReady as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            if isinstance(payload, InvestigationInput):
                result = await investigate_screening(payload.screening, context, mode=payload.mode)
            else:
                result = await run_trial(payload, context)
            run_store().save(result)
            return result
        finally:
            closer = getattr(context.model, "aclose", None)
            if closer is not None:
                try:
                    await closer()
                except Exception:
                    # Cleanup must not erase an already validated/persisted result.
                    pass

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="partial",
            agents_implemented=False,
            components={"safety": True, "interpreter": False, "evidence": True, "planner": False},
        )

    @application.post("/runs", response_model=RunResult)
    async def create_run(trial_input: TrialInput) -> RunResult:
        return await execute(trial_input)

    @application.post("/investigations", response_model=RunResult)
    async def create_investigation(payload: InvestigationInput) -> RunResult:
        """Investigate prepared screening without pretending Agent 1 is implemented."""
        return await execute(payload)

    @application.get("/runs/{run_id}", response_model=RunResult)
    def get_run(run_id: str) -> RunResult:
        result = run_store().get(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return result

    return application


app = create_app()
