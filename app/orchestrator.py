"""Run-scoped orchestration; preserve verified results across timeouts and failures."""

import asyncio
from collections.abc import Callable
from contextlib import nullcontext
from time import monotonic

from app.agents.interpreter import run_interpreter
from app.agents.safety import merged_screening, partial_report, run_safety
from app.context import ToolContext
from app.contracts import PlannerInput, PlannerReport, RunResult, ScreeningOutput, TrialInput
from app.validation import (
    planner_input_limitations,
    validate_planner_report,
    validate_run,
    validate_screening,
)

ScreeningSink = Callable[[ScreeningOutput], None]


async def investigate_screening(
    screening: ScreeningOutput,
    context: ToolContext,
    *,
    mode: str = "live",
    on_screening: ScreeningSink | None = None,
) -> RunResult:
    """Independent Agent 2 entry point for an already validated Agent 1 payload."""
    return await _run(None, screening, context, mode=mode, on_screening=on_screening)


async def run_trial(
    trial_input: TrialInput,
    context: ToolContext,
    *,
    on_screening: ScreeningSink | None = None,
) -> RunResult:
    """Interpreter -> investigator -> validated PlannerInput; Agent 4 stays deferred."""
    return await _run(
        trial_input,
        None,
        context,
        mode=trial_input.mode,
        on_screening=on_screening,
    )


async def _run(trial_input, screening, context, *, mode, on_screening=None):
    started = monotonic()
    events = []
    downstream_emit = context.emit

    def capture(event):
        events.append(event)
        downstream_emit(event)

    context.emit = capture
    errors = []
    investigation = None
    reservation = (
        context.budget.reserving_planning(min(90, context.settings.run_timeout_seconds * 0.25))
        if context.planner_handler
        else nullcontext()
    )
    try:
        with reservation:
            async with asyncio.timeout(context.budget.remaining_seconds()):
                if screening is None:
                    screening = await run_interpreter(trial_input, context)
                validate_screening(screening)
                if context.demo_profile:
                    from app.demo import DEMO_LABEL

                    screening.trial_bundle.limitations.append(DEMO_LABEL)
                if on_screening is not None:
                    on_screening(screening.model_copy(deep=True))
                context.datasets.setdefault(screening.trial_bundle.trial_id, screening.trial_bundle)
                if context.demo_profile:
                    from app.demo import run_demo_safety

                    investigation = await run_demo_safety(screening, context)
                else:
                    investigation = await run_safety(screening, context)
    except TimeoutError:
        errors.append("Run deadline exhausted; verified completed work is retained.")
    except NotImplementedError:
        errors.append("Required agent or service is not yet implemented.")
    except Exception:
        errors.append("Run could not finish; invalid or unavailable upstream result.")
    finally:
        context.emit = downstream_emit
    # Validate/merge even on error; never present an invalid upstream bundle.
    if screening is not None:
        try:
            screening = merged_screening(screening, context)
            validate_screening(screening)
        except ValueError:
            screening = None
            investigation = None
            context.evidence_reports.clear()
            errors.append("Rejected invalid screening provenance.")
    planner = None
    if screening is not None and investigation is None:
        investigation = partial_report(
            screening,
            errors[-1] if errors else "Investigation did not finish; no assessment was inferred.",
        )
    if screening is not None and investigation is not None:
        planner = PlannerInput(
            screening=screening,
            investigation=investigation,
            evidence_reports=context.evidence_reports,
        )
    planner_report = None
    context.investigation_report = investigation
    if planner is not None and context.planner_handler is not None:
        context.emit = capture
        try:
            planner_report = await context.planner_handler(planner, context)
            planner_report = PlannerReport.model_validate_json(planner_report.model_dump_json())
            validate_planner_report(planner_report, planner)
        except Exception:
            planner_report = PlannerReport(
                trial_id=screening.trial_bundle.trial_id,
                status="unavailable",
                is_synthetic=screening.trial_bundle.is_synthetic
                or any(
                    source.is_synthetic
                    for report in context.evidence_reports
                    for source in report.sources
                ),
                input_limitations=planner_input_limitations(planner),
                limitations=["Planner unavailable or rejected; upstream results are preserved."],
            )
        finally:
            context.emit = downstream_emit
        if context.demo_profile and planner_report.status == "unavailable":
            from app.demo import draft_plan_fallback

            context.emit = capture
            try:
                planner_report = draft_plan_fallback(planner, context, planner_report)
            except Exception:
                planner_report.limitations.append(
                    "Rules-based draft unavailable; verified upstream results are preserved."
                )
            finally:
                context.emit = downstream_emit
    status = "failed" if screening is None else "partial"
    context.planner_report = planner_report
    interpretation_pending = screening is not None and (
        any(mapping.needs_review for mapping in screening.symptom_mappings)
        or any(
            limitation.startswith(
                ("Interpretation incomplete", "Interpretation limited", "Follow-up interpretation")
            )
            for limitation in screening.trial_bundle.limitations
        )
    )
    if (
        investigation
        and investigation.status == "completed"
        and not errors
        and not interpretation_pending
        and all(report.status == "completed" for report in context.evidence_reports)
        and (planner_report is None or planner_report.status == "completed")
    ):
        status = "completed"
    result = RunResult(
        run_id=context.run_id,
        mode=mode,
        model_id=context.model.model_id,
        status=status,
        screening=screening,
        investigation=investigation,
        evidence_reports=context.evidence_reports,
        planner_input=planner,
        planner_report=planner_report,
        events=events,
        errors=errors,
        duration_ms=(monotonic() - started) * 1000,
    )
    validate_run(result)
    return result
