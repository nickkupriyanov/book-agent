from dataclasses import dataclass
from uuid import uuid4

import httpx
import pytest

from app.catalog.exceptions import CatalogPayloadError, CatalogUnavailableError
from app.catalog.models import CatalogBook, CatalogSearchResult, CatalogSource
from app.catalog.resilient import ResilientBookCatalog, TTLSearchCache


@dataclass
class ManualClock:
    value: float = 0

    def __call__(self) -> float:
        return self.value


class SequenceCatalog:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def search_books(self, query: str, limit: int) -> CatalogSearchResult:
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, CatalogSearchResult)
        return outcome


def result(source: CatalogSource, title: str = "Dune") -> CatalogSearchResult:
    return CatalogSearchResult(
        books=(
            CatalogBook(
                id=uuid4(),
                title=title,
                author="Author",
                tags=(),
                catalog_source=source,
            ),
        ),
        source=source,
    )


def timeout() -> httpx.TimeoutException:
    return httpx.ReadTimeout(
        "timed out",
        request=httpx.Request("GET", "https://catalog.example"),
    )


def status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://catalog.example")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("bad status", request=request, response=response)


def resilient(
    primary: SequenceCatalog,
    fallback: SequenceCatalog,
    cache: TTLSearchCache,
) -> ResilientBookCatalog:
    return ResilientBookCatalog(
        primary,
        fallback,
        cache,
        max_retries=1,
        sleeper=lambda _: None,
    )


@pytest.mark.parametrize(
    "failure",
    [
        timeout(),
        httpx.ConnectError(
            "connection failed",
            request=httpx.Request("GET", "https://catalog.example"),
        ),
        status_error(429),
        status_error(500),
    ],
)
def test_transient_failure_retries_then_uses_fallback(failure: Exception) -> None:
    primary = SequenceCatalog([failure, failure])
    fallback = SequenceCatalog([result(CatalogSource.LOCAL)])
    catalog = resilient(
        primary,
        fallback,
        TTLSearchCache(ttl_seconds=10, max_entries=2),
    )

    found = catalog.search_books("Dune", 5)

    assert primary.calls == 2
    assert fallback.calls == 1
    assert found.source is CatalogSource.LOCAL
    assert found.degraded is True
    assert found.cached is False


def test_transient_failure_can_recover_on_the_single_retry() -> None:
    external = result(CatalogSource.OPEN_LIBRARY)
    primary = SequenceCatalog([timeout(), external])
    fallback = SequenceCatalog([result(CatalogSource.LOCAL)])
    delays: list[float] = []
    catalog = ResilientBookCatalog(
        primary,
        fallback,
        TTLSearchCache(ttl_seconds=10, max_entries=2),
        max_retries=1,
        retry_delay_seconds=0.25,
        sleeper=delays.append,
    )

    found = catalog.search_books("Dune", 5)

    assert found is external
    assert primary.calls == 2
    assert fallback.calls == 0
    assert delays == [0.25]


def test_permanent_400_is_not_retried_or_hidden_by_fallback() -> None:
    primary = SequenceCatalog([status_error(400)])
    fallback = SequenceCatalog([result(CatalogSource.LOCAL)])
    catalog = resilient(
        primary,
        fallback,
        TTLSearchCache(ttl_seconds=10, max_entries=2),
    )

    with pytest.raises(CatalogUnavailableError):
        catalog.search_books("Dune", 5)

    assert primary.calls == 1
    assert fallback.calls == 0


def test_invalid_payload_falls_back_without_retry() -> None:
    primary = SequenceCatalog([CatalogPayloadError("invalid")])
    fallback = SequenceCatalog([result(CatalogSource.LOCAL)])
    catalog = resilient(
        primary,
        fallback,
        TTLSearchCache(ttl_seconds=10, max_entries=2),
    )

    found = catalog.search_books("Dune", 5)

    assert primary.calls == 1
    assert found.degraded is True


def test_fallback_result_is_not_cached() -> None:
    external = result(CatalogSource.OPEN_LIBRARY)
    primary = SequenceCatalog([timeout(), timeout(), external])
    fallback = SequenceCatalog([result(CatalogSource.LOCAL)])
    catalog = resilient(
        primary,
        fallback,
        TTLSearchCache(ttl_seconds=10, max_entries=2),
    )

    degraded = catalog.search_books("Dune", 5)
    recovered = catalog.search_books("Dune", 5)

    assert degraded.degraded is True
    assert recovered is external
    assert primary.calls == 3
    assert fallback.calls == 1


def test_successful_empty_result_is_cached_without_fallback() -> None:
    empty = CatalogSearchResult(books=(), source=CatalogSource.OPEN_LIBRARY)
    primary = SequenceCatalog([empty])
    fallback = SequenceCatalog([result(CatalogSource.LOCAL)])
    catalog = resilient(
        primary,
        fallback,
        TTLSearchCache(ttl_seconds=10, max_entries=2),
    )

    first = catalog.search_books(" DUNE ", 5)
    second = catalog.search_books("dune", 5)

    assert first.books == second.books == ()
    assert first.cached is False
    assert second.cached is True
    assert primary.calls == 1
    assert fallback.calls == 0


def test_cache_expires_and_evicts_least_recent_entry() -> None:
    clock = ManualClock()
    cache = TTLSearchCache(ttl_seconds=5, max_entries=2, clock=clock)
    primary = SequenceCatalog(
        [
            result(CatalogSource.OPEN_LIBRARY, "One"),
            result(CatalogSource.OPEN_LIBRARY, "Two"),
            result(CatalogSource.OPEN_LIBRARY, "Three"),
            result(CatalogSource.OPEN_LIBRARY, "One refreshed"),
            result(CatalogSource.OPEN_LIBRARY, "Two refreshed"),
        ]
    )
    fallback = SequenceCatalog([result(CatalogSource.LOCAL)])
    catalog = resilient(primary, fallback, cache)

    catalog.search_books("one", 1)
    catalog.search_books("two", 1)
    catalog.search_books("three", 1)
    evicted = catalog.search_books("one", 1)
    clock.value = 6
    expired = catalog.search_books("two", 1)

    assert evicted.books[0].title == "One refreshed"
    assert expired.books[0].title == "Two refreshed"
    assert primary.calls == 5


@pytest.mark.parametrize(
    ("ttl_seconds", "max_entries"),
    [(0, 1), (1, 0)],
)
def test_cache_rejects_unbounded_configuration(
    ttl_seconds: float,
    max_entries: int,
) -> None:
    with pytest.raises(ValueError):
        TTLSearchCache(ttl_seconds=ttl_seconds, max_entries=max_entries)
