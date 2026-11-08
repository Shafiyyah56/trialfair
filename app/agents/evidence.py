"""Agent 3 branch: adaptive literature search and contradictory evidence review."""

from app.context import ToolContext
from app.contracts import EvidenceReport, EvidenceRequest


async def run_evidence(request: EvidenceRequest, context: ToolContext) -> EvidenceReport:
    """Return verified retrieved citations; suggest analyses without recursive calls."""
    raise NotImplementedError("Agent 3: implement run_evidence on feat/agent-3-evidence")
