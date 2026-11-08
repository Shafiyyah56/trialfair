"""Agent 1 owns terminology lookup; do not invent licensed vocabulary codes."""

from typing import Protocol

from app.contracts import TerminologyCandidate


class TerminologyService(Protocol):
    async def lookup(self, text: str) -> list[TerminologyCandidate]: ...
