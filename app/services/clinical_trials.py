"""Agent 1 owns registry ingestion; Agent 3 reuses this same service interface."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import JsonValue

from app.contracts import SourceRecord, TrialSearchHit


@dataclass(frozen=True)
class RetrievedTrial:
    """Raw API v2 response plus retrieval provenance; parsing belongs to Agent 1."""

    payload: dict[str, JsonValue]
    source: SourceRecord


class ClinicalTrialsService(Protocol):
    async def fetch_trial(self, nct_id: str) -> RetrievedTrial: ...

    async def search_related_trials(
        self, query: str, *, page_size: int = 5
    ) -> list[TrialSearchHit]: ...
