from collections import OrderedDict
from collections.abc import Callable
from dataclasses import replace
from threading import Lock
from time import monotonic, sleep

import httpx

from app.catalog.exceptions import CatalogPayloadError, CatalogUnavailableError
from app.catalog.models import CatalogSearchResult
from app.catalog.provider import BookCatalog


class TTLSearchCache:
    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_entries: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[
            tuple[str, int], tuple[float, CatalogSearchResult]
        ] = OrderedDict()
        self._lock = Lock()

    def get(self, key: tuple[str, int]) -> CatalogSearchResult | None:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, result = entry
            if expires_at <= now:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return result

    def put(self, key: tuple[str, int], result: CatalogSearchResult) -> None:
        with self._lock:
            self._entries[key] = (self._clock() + self._ttl_seconds, result)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)


class ResilientBookCatalog:
    def __init__(
        self,
        primary: BookCatalog,
        fallback: BookCatalog,
        cache: TTLSearchCache,
        *,
        max_retries: int,
        retry_delay_seconds: float = 0,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._cache = cache
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._sleeper = sleeper

    def search_books(self, query: str, limit: int) -> CatalogSearchResult:
        key = (_normalize_query(query), limit)
        cached = self._cache.get(key)
        if cached is not None:
            return replace(cached, cached=True)

        for attempt in range(self._max_retries + 1):
            try:
                result = self._primary.search_books(query, limit)
            except CatalogPayloadError:
                return self._fallback_search(query, limit)
            except httpx.TransportError:
                if attempt == self._max_retries:
                    return self._fallback_search(query, limit)
                self._sleeper(self._retry_delay_seconds)
            except httpx.HTTPStatusError as exc:
                if not _is_transient_status(exc.response.status_code):
                    raise CatalogUnavailableError(
                        "External catalog request was rejected"
                    ) from exc
                if attempt == self._max_retries:
                    return self._fallback_search(query, limit)
                self._sleeper(self._retry_delay_seconds)
            else:
                self._cache.put(key, result)
                return result

        raise AssertionError("catalog retry loop did not terminate")

    def _fallback_search(self, query: str, limit: int) -> CatalogSearchResult:
        return replace(
            self._fallback.search_books(query, limit),
            degraded=True,
            cached=False,
        )


def _normalize_query(query: str) -> str:
    normalized = " ".join(query.split()).casefold()
    if not normalized:
        raise ValueError("query must not be blank")
    return normalized


def _is_transient_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500
