"""Local research API with injected runtimes and validated persisted results.

The default runtime connects Agents 1–3 to the registry and Europe PMC. Unavailable
sources never become fake live results. Bind to localhost for the hackathon;
there is no account or public-hosting security layer in this MVP.
"""

import asyncio
from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from app.config import Settings
from app.context import ToolContext
from app.contracts import Contract, HealthResponse, RunResult, ScreeningOutput, TrialInput
from app.orchestrator import investigate_screening, run_trial
from app.progress import ActiveRunRegistry, RunAccepted, RunProgress
from app.runtime import RuntimeNotReady, build_context
from app.storage import RunStore, SQLiteRunStore
from app.synthetic_upload import SyntheticUpload, load_upload, register_upload, upload_preview


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
    active_runs = ActiveRunRegistry()
    application.state.run_tasks = set()

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
            await context.aclose()

    async def execute_in_background(payload, context: ToolContext) -> None:
        try:

            def screening_sink(screening: ScreeningOutput) -> None:
                active_runs.screening_ready(context.run_id, screening)

            if isinstance(payload, InvestigationInput):
                result = await investigate_screening(
                    payload.screening,
                    context,
                    mode=payload.mode,
                    on_screening=screening_sink,
                )
            else:
                result = await run_trial(payload, context, on_screening=screening_sink)
            run_store().save(result)
            active_runs.finish(result)
        except Exception:
            active_runs.fail(
                context.run_id,
                "The run stopped before a validated result could be saved.",
            )
        finally:
            await context.aclose()

    def start_background_run(payload, *, demo=False) -> RunAccepted:
        if demo:
            from app.demo import DEMO_TRIAL, build_demo_context, configure_demo_context

            if payload.nct_id != DEMO_TRIAL or payload.mode != "live":
                raise HTTPException(422, "Curated demo requires NCT04280705 and live model mode.")
            factory = context_factory or build_demo_context
        else:
            factory = context_factory or build_context
        run_id = str(uuid4())
        try:
            context = factory(run_id, payload.mode)
            if demo and context_factory is not None:
                context = configure_demo_context(context)
        except RuntimeNotReady as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return queue_background_run(payload, context)

    def queue_background_run(payload, context):
        run_id = context.run_id
        active_runs.start(
            run_id, includes_interpretation=not isinstance(payload, InvestigationInput)
        )
        downstream_emit = context.emit

        def capture(event):
            active_runs.record_event(
                run_id,
                event,
                context.evidence_reports,
                investigation=context.investigation_report,
                planner_report=context.planner_report,
            )
            downstream_emit(event)

        context.emit = capture
        task = asyncio.create_task(execute_in_background(payload, context))
        application.state.run_tasks.add(task)
        task.add_done_callback(application.state.run_tasks.discard)
        return RunAccepted(run_id=run_id, progress_url=f"/runs/{run_id}/progress")

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ready",
            agents_implemented=True,
            # Implementation flags, not credential/source connectivity checks.
            components={"safety": True, "interpreter": True, "evidence": True, "planner": True},
        )

    @application.post("/runs", response_model=RunResult)
    async def create_run(trial_input: TrialInput) -> RunResult:
        return await execute(trial_input)

    @application.post("/investigations", response_model=RunResult)
    async def create_investigation(payload: InvestigationInput) -> RunResult:
        """Investigate a prepared screening without repeating trial ingestion."""
        return await execute(payload)

    @application.post("/runs/async", response_model=RunAccepted, status_code=202)
    async def create_run_async(trial_input: TrialInput) -> RunAccepted:
        """Start a trial run and return immediately for honest progress polling."""
        return start_background_run(trial_input)

    @application.post("/investigations/async", response_model=RunAccepted, status_code=202)
    async def create_investigation_async(payload: InvestigationInput) -> RunAccepted:
        """Start prepared-screening investigation without repeating interpretation."""
        return start_background_run(payload)

    @application.post("/demo/runs/async", response_model=RunAccepted, status_code=202)
    async def create_demo_run(trial_input: TrialInput) -> RunAccepted:
        """Explicit curated remdesivir demo with captured sources and live model stages."""
        return start_background_run(trial_input, demo=True)

    @application.post("/synthetic/preview")
    async def preview_synthetic_upload(payload: SyntheticUpload):
        try:
            return upload_preview(payload)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @application.post("/synthetic/runs/async", response_model=RunAccepted, status_code=202)
    async def create_synthetic_run(payload: SyntheticUpload):
        from app.demo import build_demo_context

        try:
            bundle = load_upload(payload)  # Validate before constructing a paid model runtime.
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
        run_id = str(uuid4())
        try:
            context = (
                context_factory(run_id, "live")
                if context_factory
                else build_demo_context(run_id, "live", registry_capture=False)
            )
        except RuntimeNotReady as exc:
            raise HTTPException(503, str(exc)) from exc
        trial_input = register_upload(context, payload, bundle)
        return queue_background_run(trial_input, context)

    @application.get("/runs/{run_id}/progress", response_model=RunProgress)
    def get_run_progress(run_id: str) -> RunProgress:
        progress = active_runs.get(run_id)
        if progress is None:
            raise HTTPException(status_code=404, detail="Active run not found")
        return progress

    @application.get("/runs/{run_id}", response_model=RunResult)
    def get_run(run_id: str) -> RunResult:
        result = run_store().get(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return result

    return application


app = create_app()
