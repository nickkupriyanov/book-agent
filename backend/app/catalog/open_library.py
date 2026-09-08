import re
from collections.abc import Mapping
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.catalog.exceptions import CatalogPayloadError
from app.catalog.models import CatalogBook, CatalogSearchResult, CatalogSource

OPEN_LIBRARY_FIELDS = "key,title,author_name,isbn,cover_i,subject_key"
_WORK_ID = re.compile(r"^OL\d+W$")
_ISBN_10 = re.compile(r"^\d{9}[\dX]$")
_ISBN_13 = re.compile(r"^\d{13}$")


class OpenLibrarySearchTransport(Protocol):
    def search(self, query: str, limit: int) -> object: ...


class HttpOpenLibraryTransport:
    def __init__(
        self,
        client: httpx.Client,
        *,
        base_url: str = "https://openlibrary.org",
        user_agent: str = "BookAgentLearning/0.1",
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent

    def search(self, query: str, limit: int) -> object:
        response = self._client.get(
            f"{self._base_url}/search.json",
            params={"q": query, "limit": limit, "fields": OPEN_LIBRARY_FIELDS},
            headers={"User-Agent": self._user_agent},
        )
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise CatalogPayloadError(
                "Open Library returned invalid JSON"
            ) from exc


class OpenLibraryCatalog:
    def __init__(self, transport: OpenLibrarySearchTransport) -> None:
        self._transport = transport

    def search_books(self, query: str, limit: int) -> CatalogSearchResult:
        if not query.strip():
            raise ValueError("query must not be blank")
        if limit < 1:
            raise ValueError("limit must be at least 1")

        return CatalogSearchResult(
            books=normalize_open_library_payload(
                self._transport.search(query, limit),
                limit=limit,
            ),
            source=CatalogSource.OPEN_LIBRARY,
        )


def normalize_open_library_payload(
    payload: object,
    *,
    limit: int,
) -> tuple[CatalogBook, ...]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("docs"), list):
        raise CatalogPayloadError("Open Library returned an invalid search payload")

    books: list[CatalogBook] = []
    seen_work_ids: set[str] = set()
    for document in payload["docs"]:
        book = _normalize_document(document)
        if book is None or book.external_id in seen_work_ids:
            continue
        books.append(book)
        if book.external_id is not None:
            seen_work_ids.add(book.external_id)
        if len(books) == limit:
            break
    return tuple(books)


def _normalize_document(document: object) -> CatalogBook | None:
    if not isinstance(document, Mapping):
        return None

    work_id = _normalize_work_id(document.get("key"))
    title = _clean_text(document.get("title"))
    if work_id is None or title is None:
        return None

    authors = _clean_string_list(document.get("author_name"))
    return CatalogBook(
        id=uuid5(NAMESPACE_URL, f"https://openlibrary.org/works/{work_id}"),
        title=title,
        author=", ".join(authors) if authors else "Unknown author",
        tags=_normalize_tags(document.get("subject_key")),
        catalog_source=CatalogSource.OPEN_LIBRARY,
        external_id=work_id,
        isbn=_select_isbn(document.get("isbn")),
        cover_url=_cover_url(document.get("cover_i")),
    )


def _normalize_work_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    work_id = value.removeprefix("/works/").strip()
    return work_id if _WORK_ID.fullmatch(work_id) else None


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _clean_string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    cleaned = (_clean_text(item) for item in value)
    return tuple(dict.fromkeys(item for item in cleaned if item is not None))


def _select_isbn(value: object) -> str | None:
    candidates: list[str] = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, str):
                continue
            candidate = re.sub(r"[-\s]", "", item).upper()
            if _ISBN_13.fullmatch(candidate) or _ISBN_10.fullmatch(candidate):
                candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates, key=lambda item: (len(item) != 13, item))


def _cover_url(value: object) -> str | None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    return f"https://covers.openlibrary.org/b/id/{value}-M.jpg"


def _normalize_tags(value: object) -> tuple[str, ...]:
    tags = []
    for item in _clean_string_list(value):
        tag = re.sub(r"[^\w]+", "_", item.casefold(), flags=re.UNICODE).strip("_")
        if tag:
            tags.append(tag)
    return tuple(sorted(set(tags))[:20])
