"""Agent 2 integration owner: assemble screening, investigation and future planner input."""

from app.context import ToolContext
from app.contracts import RunResult, TrialInput


async def run_trial(trial_input: TrialInput, context: ToolContext) -> RunResult:
    """Enforce one deadline and validate provenance before returning a run."""
    raise NotImplementedError("Agent 2: integrate agents and assemble PlannerInput")
