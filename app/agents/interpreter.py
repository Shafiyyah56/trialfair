"""Agent 1 branch: narrative interpretation, registry parsing and Python screening."""

from app.context import ToolContext
from app.contracts import ScreeningOutput, TrialInput


async def run_interpreter(trial_input: TrialInput, context: ToolContext) -> ScreeningOutput:
    """Return source-linked screening; implementation belongs to Agent 1."""
    raise NotImplementedError("Agent 1: implement run_interpreter on feat/agent-1-interpreter")
