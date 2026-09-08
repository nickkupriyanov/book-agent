import httpx
import pytest

from app.catalog.exceptions import CatalogPayloadError
from app.catalog.models import CatalogSource
from app.catalog.open_library import (
    OPEN_LIBRARY_FIELDS,
    HttpOpenLibraryTransport,
    OpenLibraryCatalog,
    normalize_open_library_payload,
)


class StubTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> object:
        self.calls.append((query, limit))
        return self.payload


def test_catalog_normalizes_work_and_ignores_damaged_documents() -> None:
    transport = StubTransport(
        {
            "docs": [
                {
                    "key": "/works/OL123W",
                    "title": "  A   Book ",
                    "author_name": [" Ada  Author ", "Ben Writer"],
                    "isbn": ["0-12345678-X", "978-0-306-40615-7"],
                    "cover_i": 42,
                    "subject_key": ["Science Fiction", "space-opera"],
                },
                {"key": "/books/OL1M", "title": "An edition"},
                {"key": "/works/OL999W"},
                "not an object",
            ]
        }
    )

    result = OpenLibraryCatalog(transport).search_books("A Book", 10)

    assert transport.calls == [("A Book", 10)]
    assert result.source is CatalogSource.OPEN_LIBRARY
    assert result.degraded is False
    assert result.cached is False
    assert len(result.books) == 1
    book = result.books[0]
    assert str(book.id) == "25b6648b-432f-54ea-bb4b-93dadb2995af"
    assert book.external_id == "OL123W"
    assert book.title == "A Book"
    assert book.author == "Ada Author, Ben Writer"
    assert book.isbn == "9780306406157"
    assert book.cover_url == "https://covers.openlibrary.org/b/id/42-M.jpg"
    assert book.tags == ("science_fiction", "space_opera")


def test_catalog_accepts_missing_optional_metadata_and_deduplicates_work() -> None:
    result = normalize_open_library_payload(
        {
            "docs": [
                {"key": "OL7W", "title": "Untitled Author"},
                {"key": "/works/OL7W", "title": "Duplicate"},
            ]
        },
        limit=5,
    )

    assert len(result) == 1
    assert result[0].author == "Unknown author"
    assert result[0].isbn is None
    assert result[0].cover_url is None
    assert result[0].tags == ()


@pytest.mark.parametrize("payload", [None, [], {}, {"docs": "wrong"}])
def test_catalog_rejects_invalid_root_payload(payload: object) -> None:
    with pytest.raises(CatalogPayloadError):
        normalize_open_library_payload(payload, limit=10)


def test_http_transport_uses_only_explicit_fields_and_user_agent() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search.json"
        assert request.url.params["q"] == "Dune"
        assert request.url.params["limit"] == "3"
        assert request.url.params["fields"] == OPEN_LIBRARY_FIELDS
        assert request.headers["user-agent"] == "BookAgentTest/1.0"
        return httpx.Response(200, json={"docs": []})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    transport = HttpOpenLibraryTransport(
        client,
        base_url="https://catalog.example/",
        user_agent="BookAgentTest/1.0",
    )

    assert transport.search("Dune", 3) == {"docs": []}


def test_http_transport_converts_invalid_json_to_catalog_error() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="not-json")
        )
    )
    transport = HttpOpenLibraryTransport(client)

    with pytest.raises(CatalogPayloadError, match="invalid JSON"):
        transport.search("Dune", 3)


def test_catalog_rejects_invalid_input_before_transport() -> None:
    transport = StubTransport({"docs": []})
    catalog = OpenLibraryCatalog(transport)

    with pytest.raises(ValueError, match="blank"):
        catalog.search_books("  ", 10)
    with pytest.raises(ValueError, match="limit"):
        catalog.search_books("Dune", 0)

    assert transport.calls == []
