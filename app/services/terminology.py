"""Agent 1 owns terminology lookup; do not invent licensed vocabulary codes."""

from typing import Protocol

from app.contracts import TerminologyCandidate


class TerminologyService(Protocol):
    async def lookup(self, text: str) -> list[TerminologyCandidate]: ...


class SuppliedTerminology:
    """Exact lookup of supplied mappings only; an empty mapping is a safe default.

    The caller is responsible for licensing and registering candidate sources.
    No guessed vocabulary codes or fuzzy clinical equivalences are generated.
    """

    def __init__(self, mappings: dict[str, list[TerminologyCandidate]] | None = None):
        self._mappings = mappings or {}

    async def lookup(self, text: str) -> list[TerminologyCandidate]:
        return [candidate.model_copy(deep=True) for candidate in self._mappings.get(text, [])]
