"""Real adapter logic with explicit synthetic API payloads and httpx.MockTransport."""

import asyncio
import json
from datetime import timedelta

import httpx
import pytest

from app.config import Settings
from app.context import BudgetExceeded, RunBudget
from app.services.europe_pmc import EuropePMCClient, LiteratureUnavailable


def api_record(**overrides):
    """Not a real article; identifiers and prose are synthetic transport-test data."""
    value = {
        "source": "MED",
        "id": "999999999",
        "title": "Synthetic test article",
        "abstractText": "<p>Test women had <i>higher</i> exposure. No clinical claim is made.</p>",
        "doi": "10.99999/trialfair-test-only",
        "pubYear": "2026",
        "pmcid": "PMC999999999",
        "isOpenAccess": "Y",
        "authorList": {"author": [{"fullName": "Synthetic Author"}]},
    }
    value.update(overrides)
    return value


def make_client(handler, tmp_path=None, **settings):
    budget = RunBudget.from_settings(Settings(_env_file=None, **settings))
    client = EuropePMCClient(
        budget,
        cache_dir=tmp_path,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return client, budget


def search_payload(records):
    return {"resultList": {"result": records}}


def test_core_search_metadata_and_cached_provenance(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=search_payload([api_record()]))

    client, budget = make_client(handler, tmp_path)

    async def scenario():
        first = await client.search_publications("test question")
        second = await client.search_publications("test question")
        await client.http_client.aclose()
        return first, second

    first, second = asyncio.run(scenario())
    assert len(requests) == 1
    assert requests[0].url.params["resultType"] == "core"
    assert requests[0].url.host == "www.ebi.ac.uk"
    assert first == second
    record = first[0]
    assert record.abstract == "Test women had higher exposure. No clinical claim is made."
    assert record.source.access_level == "abstract"
    assert record.source.licence_status == "unknown"
    assert record.source.retrieved_at.tzinfo is not None
    assert len(record.source.content_hash) == 64
    assert budget.used["external_request"] == 1
    assert client.last_cache_hit
    fresh, fresh_budget = make_client(
        lambda r: pytest.fail("Disk cache should satisfy request"), tmp_path
    )
    cached = asyncio.run(fresh.search_publications("test question"))
    asyncio.run(fresh.http_client.aclose())
    assert cached == first
    assert not fresh_budget.used


def test_duplicate_dois_not_independent_results():
    client, _ = make_client(
        lambda r: httpx.Response(
            200,
            json=search_payload(
                [
                    api_record(),
                    api_record(id="999999998", doi="10.99999/TRIALFAIR-TEST-ONLY"),
                ]
            ),
        )
    )
    records = asyncio.run(client.search_publications("test"))
    assert len(records) == 1
    asyncio.run(client.http_client.aclose())


def test_metadata_only_and_explicit_licence():
    client, _ = make_client(
        lambda r: httpx.Response(
            200,
            json=search_payload(
                [
                    api_record(abstractText=None, license="CC BY 4.0", isOpenAccess="N"),
                ]
            ),
        )
    )
    record = asyncio.run(client.search_publications("test"))[0]
    assert record.source.access_level == "metadata"
    assert record.source.licence_status == "verified"
    assert not record.full_text_available
    asyncio.run(client.http_client.aclose())


def test_open_access_body_and_license_are_retrieved():
    def handler(request):
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=search_payload([api_record()]))
        return httpx.Response(
            200,
            text="""<?xml version="1.0"?><article>
        <front><article-meta><permissions><license xmlns:xlink="http://www.w3.org/1999/xlink"
        xlink:href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</license>
        </permissions></article-meta></front><body><sec><title>Test results</title>
        <p>Synthetic body evidence only.</p></sec></body></article>""",
        )

    client, budget = make_client(handler)

    async def scenario():
        await client.search_publications("test")
        result = await client.fetch_open_access_full_text("PMC999999999")
        await client.http_client.aclose()
        return result

    text, source = asyncio.run(scenario())
    assert "Synthetic body evidence" in text
    assert source.access_level == "full_text"
    assert source.licence_status == "verified"
    assert str(source.licence_url).startswith("https://creativecommons.org/")
    assert budget.used["external_request"] == 2


def test_non_open_access_full_text_fails_without_fetching_body():
    client, budget = make_client(
        lambda r: httpx.Response(
            200,
            json=search_payload(
                [
                    api_record(isOpenAccess="N"),
                ]
            ),
        )
    )
    asyncio.run(client.search_publications("test"))
    with pytest.raises(LiteratureUnavailable, match="not available"):
        asyncio.run(client.fetch_open_access_full_text("PMC999999999"))
    assert budget.used["external_request"] == 1
    asyncio.run(client.http_client.aclose())


@pytest.mark.parametrize("status", [429, 503, 302])
def test_source_errors_do_not_leak_provider_content(status):
    client, _ = make_client(
        lambda r: httpx.Response(
            status, text="private-provider-detail", headers={"Location": "https://example.com"}
        )
    )
    with pytest.raises(LiteratureUnavailable) as error:
        asyncio.run(client.search_publications("test"))
    assert "private-provider-detail" not in str(error.value)
    asyncio.run(client.http_client.aclose())


def test_budget_exhaustion_prevents_second_external_request():
    client, budget = make_client(
        lambda r: httpx.Response(200, json=search_payload([])), max_external_requests=1
    )
    assert asyncio.run(client.search_publications("first")) == []
    with pytest.raises(BudgetExceeded):
        asyncio.run(client.search_publications("second"))
    assert budget.used["external_request"] == 1
    asyncio.run(client.http_client.aclose())


def test_stale_disk_cache_is_refetched(tmp_path):
    client, _ = make_client(lambda r: httpx.Response(200, json=search_payload([])), tmp_path)
    asyncio.run(client.search_publications("test"))
    cache = next(tmp_path.glob("*.json"))
    stored = json.loads(cache.read_text())
    from datetime import datetime

    stored["retrieved_at"] = (
        datetime.fromisoformat(stored["retrieved_at"]) - timedelta(days=2)
    ).isoformat()
    cache.write_text(json.dumps(stored))
    fresh, budget = make_client(lambda r: httpx.Response(200, json=search_payload([])), tmp_path)
    asyncio.run(fresh.search_publications("test"))
    assert budget.used["external_request"] == 1
    assert not fresh.last_cache_hit
    asyncio.run(client.http_client.aclose())
    asyncio.run(fresh.http_client.aclose())


@pytest.mark.parametrize("query,page_size", [("", 5), ("test", 6), ("test", 0)])
def test_invalid_queries_rejected_before_network(query, page_size):
    client, budget = make_client(lambda r: pytest.fail("No network call expected"))
    with pytest.raises(ValueError):
        asyncio.run(client.search_publications(query, page_size=page_size))
    assert not budget.used
    asyncio.run(client.http_client.aclose())


def test_invalid_lookup_identifier_cannot_inject_query():
    client, _ = make_client(lambda r: pytest.fail("No network call expected"))
    with pytest.raises(ValueError):
        asyncio.run(client.fetch_publication_metadata("MED", '123" OR *'))
    asyncio.run(client.http_client.aclose())


def test_malformed_response_not_interpreted_as_no_evidence():
    client, _ = make_client(lambda r: httpx.Response(200, json={"unexpected": []}))
    with pytest.raises(LiteratureUnavailable, match="Malformed"):
        asyncio.run(client.search_publications("test"))
    asyncio.run(client.http_client.aclose())


def test_oversized_response_rejected(monkeypatch):
    from app.services import europe_pmc

    monkeypatch.setattr(europe_pmc, "MAX_RESPONSE_BYTES", 50)
    client, _ = make_client(lambda r: httpx.Response(200, text="x" * 51))
    with pytest.raises(LiteratureUnavailable, match="size limit"):
        asyncio.run(client.search_publications("test"))
    asyncio.run(client.http_client.aclose())
