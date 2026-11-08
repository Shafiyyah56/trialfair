"""Agent 2 branch: hypothesis investigation and bounded tool selection."""

from app.context import ToolContext
from app.contracts import InvestigationReport, ScreeningOutput


async def run_safety(screening: ScreeningOutput, context: ToolContext) -> InvestigationReport:
    """Use injected handlers to request analyses and external evidence in process."""
    raise NotImplementedError("Agent 2: implement run_safety on feat/agent-2-safety")
