"""Agent 1 branch: allowlisted deterministic tools, never model-generated code."""

from app.context import ToolContext
from app.contracts import AnalysisRequest, AnalysisResult


async def execute_analysis(request: AnalysisRequest, context: ToolContext) -> AnalysisResult:
    """Resolve validated dataset refs; reject analyses unsupported by available data."""
    raise NotImplementedError("Agent 1: implement execute_analysis on feat/agent-1-interpreter")
