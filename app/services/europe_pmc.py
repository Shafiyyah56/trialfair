"""Agent 3 owns the Europe PMC adapter; metadata is distinct from full-text access."""

from typing import Protocol

from app.contracts import PublicationRecord, SourceRecord


class EuropePMCService(Protocol):
    async def search_publications(
        self, query: str, *, page_size: int = 5
    ) -> list[PublicationRecord]: ...

    async def fetch_publication_metadata(
        self, source: str, external_id: str
    ) -> PublicationRecord: ...

    async def fetch_open_access_full_text(self, pmcid: str) -> tuple[str, SourceRecord]: ...
