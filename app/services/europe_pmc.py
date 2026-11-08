"""Europe PMC search and permitted open-access retrieval with bounded provenance.

The Protocol is unchanged. EuropePMCClient uses public HTTPS endpoints only, one
shared run budget, bounded response sizes and a local raw-response cache. Search
uses resultType=core so abstract availability is never inferred from a title.
Article-specific licence metadata remains unknown when the provider omits it.
"""

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree

import httpx

from app.contracts import PublicationRecord, SourceRecord

BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
MAX_RESPONSE_BYTES = 3_000_000


class EuropePMCService(Protocol):
    async def search_publications(
        self, query: str, *, page_size: int = 5
    ) -> list[PublicationRecord]: ...

    async def fetch_publication_metadata(
        self, source: str, external_id: str
    ) -> PublicationRecord: ...

    async def fetch_open_access_full_text(self, pmcid: str) -> tuple[str, SourceRecord]: ...


class LiteratureUnavailable(RuntimeError):
    """Safe public error without provider headers, credential URLs or raw payloads."""


class _PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(text: str) -> str:
    parser = _PlainHTML()
    parser.feed(text)
    return " ".join(" ".join(parser.parts).split())


def publication_identity(record: PublicationRecord) -> str:
    """Stable work identity for deduplication; not evidence of independent replication."""
    if record.doi:
        return "doi:" + record.doi.lower().removeprefix("https://doi.org/")
    if record.pmid:
        return "pmid:" + record.pmid
    if record.pmcid:
        return "pmcid:" + record.pmcid
    return record.source.external_id or record.source.source_id


def publication_keys(record: PublicationRecord) -> set[str]:
    """All available work identifiers, so a missing DOI does not hide a duplicate PMID."""
    keys = {publication_identity(record)}
    if record.pmid:
        keys.add("pmid:" + record.pmid)
    if record.pmcid:
        keys.add("pmcid:" + record.pmcid)
    if record.source.external_id:
        keys.add("external:" + record.source.external_id)
    return keys


class EuropePMCClient:
    """Construct per run using context.budget; no network or files at construction."""

    def __init__(self, budget, *, cache_dir: Path | None = None, http_client=None):
        self.budget = budget
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.http_client = http_client
        self.last_cache_hit = False
        self._memory = {}
        self._records = {}
        self._pmc_metadata = {}

    async def _get(self, path: str, *, params=None) -> tuple[bytes, datetime]:
        """Allowlisted paths, no redirects/retries, hard size and deadline limits."""
        self.budget.remaining_seconds()
        if path != "/search" and not re.fullmatch(r"/PMC\d+/fullTextXML", path):
            raise ValueError("Unsupported literature endpoint")
        key = hashlib.sha256(json.dumps([path, params], sort_keys=True).encode()).hexdigest()
        cached = self._memory.get(key)
        cache_path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if cached is None and cache_path is not None and cache_path.exists():
            try:
                if cache_path.stat().st_size <= MAX_RESPONSE_BYTES * 2:
                    stored = json.loads(cache_path.read_text())
                    raw = stored["body"].encode()
                    stamp = datetime.fromisoformat(stored["retrieved_at"])
                    if stamp.tzinfo and hashlib.sha256(raw).hexdigest() == stored["sha256"]:
                        cached = (raw, stamp)
            except (ValueError, KeyError, OSError):
                cached = None
        if cached and timedelta(0) <= datetime.now(UTC) - cached[1] < timedelta(hours=24):
            self.last_cache_hit = True
            self._memory[key] = cached
            return cached
        self.last_cache_hit = False
        self.budget.consume("external_request")
        try:
            async with asyncio.timeout(self.budget.remaining_seconds()):
                if self.http_client is None:
                    async with httpx.AsyncClient(follow_redirects=False) as client:
                        raw = await self._download(client, path, params)
                else:
                    raw = await self._download(self.http_client, path, params)
        except (httpx.HTTPError, UnicodeError) as exc:
            raise LiteratureUnavailable("Literature service request failed") from exc
        stamp = datetime.now(UTC)
        self._memory[key] = (raw, stamp)
        if cache_path is not None:
            # Cache failures must not invalidate an otherwise successful source request.
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                stored = {
                    "body": raw.decode(),
                    "retrieved_at": stamp.isoformat(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
                temporary = cache_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(stored))
                temporary.replace(cache_path)
            except (OSError, UnicodeError):
                pass
        return raw, stamp

    async def _download(self, client, path, params):
        async with client.stream(
            "GET",
            BASE_URL + path,
            params=params,
            timeout=min(12, self.budget.remaining_seconds()),
            follow_redirects=False,
            headers={"Accept": "application/json" if path == "/search" else "application/xml"},
        ) as response:
            response.raise_for_status()
            chunks = []
            size = 0
            async for chunk in response.aiter_bytes():
                self.budget.remaining_seconds()
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise LiteratureUnavailable("Literature response exceeds the size limit")
                chunks.append(chunk)
            return b"".join(chunks)

    def _record(self, item: dict, stamp: datetime) -> PublicationRecord:
        source_code = str(item.get("source", "")).upper()
        external_id = str(item.get("id", ""))
        if not re.fullmatch(r"[A-Z]{2,8}", source_code) or not re.fullmatch(
            r"[A-Za-z0-9._-]{1,100}", external_id
        ):
            raise LiteratureUnavailable("Publication record has no usable source identifier")
        title = plain_text(str(item.get("title", "")))
        if not title:
            raise LiteratureUnavailable("Publication record has no title")
        digest = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        source_id = f"epmc-{source_code.lower()}-{external_id}-{digest[:12]}"
        if source_id in self._records:
            return self._records[source_id]
        abstract = plain_text(item.get("abstractText") or "") or None
        licence = item.get("license")
        licence = licence.strip() if isinstance(licence, str) and licence.strip() else None
        doi = item.get("doi")
        doi = doi if isinstance(doi, str) and re.fullmatch(r"10\.\d{4,9}/\S+", doi) else None
        pmid = external_id if source_code == "MED" and external_id.isdigit() else item.get("pmid")
        pmid = str(pmid) if pmid and str(pmid).isdigit() else None
        pmcid = item.get("pmcid") or (external_id if source_code == "PMC" else None)
        pmcid = pmcid if isinstance(pmcid, str) and re.fullmatch(r"PMC\d+", pmcid) else None
        year = str(item.get("pubYear", ""))
        authors = [
            str(x.get("fullName"))
            for x in item.get("authorList", {}).get("author", [])
            if isinstance(x, dict) and x.get("fullName")
        ]
        source = SourceRecord(
            source_id=source_id,
            source_type="publication",
            title=title,
            url=f"https://europepmc.org/article/{source_code}/{external_id}",
            external_id=f"{source_code}:{external_id}",
            retrieved_at=stamp,
            content_hash=digest,
            licence_name=licence,
            licence_status="verified" if licence else "unknown",
            access_level="abstract" if abstract else "metadata",
            is_synthetic=False,
        )
        record = PublicationRecord(
            source=source,
            authors=authors,
            year=int(year) if year.isdigit() else None,
            doi=doi,
            pmid=pmid,
            pmcid=pmcid,
            abstract=abstract,
            full_text_available=bool(pmcid and item.get("isOpenAccess") == "Y"),
        )
        self._records[source_id] = record
        if pmcid:
            self._pmc_metadata[pmcid] = record
        return record

    async def search_publications(self, query: str, *, page_size: int = 5):
        if not query.strip() or len(query) > 1000 or not 1 <= page_size <= 5:
            raise ValueError("Search query or result limit is invalid")
        raw, stamp = await self._get(
            "/search",
            params={
                "query": query,
                "format": "json",
                "resultType": "core",
                "pageSize": page_size,
            },
        )
        try:
            payload = json.loads(raw)
            items = payload["resultList"]["result"]
            if not isinstance(items, list):
                raise ValueError("Invalid result list")
            records = []
            seen_keys = set()
            for item in items[:page_size]:
                record = self._record(item, stamp)
                keys = publication_keys(record)
                if not keys & seen_keys:
                    records.append(record)
                seen_keys.update(keys)
            return records
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise LiteratureUnavailable("Malformed literature response") from exc

    async def fetch_publication_metadata(self, source: str, external_id: str):
        source = source.upper()
        if not re.fullmatch(r"[A-Z]{2,8}", source) or not re.fullmatch(
            r"[A-Za-z0-9._-]{1,100}", external_id
        ):
            raise ValueError("Invalid publication lookup identifier")
        results = await self.search_publications(
            f'EXT_ID:"{external_id}" AND SRC:{source}',
            page_size=1,
        )
        for record in results:
            if record.source.external_id == f"{source}:{external_id}":
                return record
        raise LiteratureUnavailable("Publication metadata not found")

    async def fetch_open_access_full_text(self, pmcid: str):
        if not re.fullmatch(r"PMC\d+", pmcid):
            raise ValueError("Invalid PMCID")
        record = self._pmc_metadata.get(pmcid)
        if record is None:
            record = await self.fetch_publication_metadata("PMC", pmcid)
        if not record.full_text_available:
            raise LiteratureUnavailable("Open-access full text is not available for this record")
        raw, stamp = await self._get(f"/{pmcid}/fullTextXML")
        # ElementTree does not fetch external DTDs; reject internal entity declarations.
        if b"<!ENTITY" in raw.upper():
            raise LiteratureUnavailable("Unsupported entities in article XML")
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError as exc:
            raise LiteratureUnavailable("Malformed article XML") from exc
        body = root.find(".//body")
        if body is None:
            raise LiteratureUnavailable("No article body was returned")
        text = " ".join(" ".join(body.itertext()).split())
        if not text:
            raise LiteratureUnavailable("Article body is empty")
        digest = hashlib.sha256(raw).hexdigest()
        licence = root.find(".//license")
        licence_name = record.source.licence_name
        licence_url = None
        if licence is not None:
            href = licence.attrib.get("{http://www.w3.org/1999/xlink}href")
            if href and href.startswith(("https://", "http://")):
                licence_url = href
            licence_name = " ".join(" ".join(licence.itertext()).split()) or licence_name
        source_id = f"epmc-{pmcid}-fulltext-{digest[:12]}"
        source = SourceRecord(
            source_id=source_id,
            source_type="publication",
            title=record.source.title,
            url=f"https://europepmc.org/articles/{pmcid}",
            external_id=pmcid,
            retrieved_at=stamp,
            content_hash=digest,
            licence_name=licence_name,
            licence_url=licence_url,
            licence_status="verified" if licence_name else "unknown",
            access_level="full_text",
            is_synthetic=False,
        )
        return text, source
