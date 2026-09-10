from unittest.mock import create_autospec
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.catalog.exceptions import CatalogUnavailableError
from app.catalog.models import CatalogBook, CatalogSearchResult, CatalogSource
from app.repository import BookRepository
from app.service import BookService
from app.tools.books import (
    BookToolResult,
    SearchBooksArguments,
    SearchBooksHandler,
    SearchBooksResult,
)
from app.tools.exceptions import ToolExecutionError
from app.tools.models import ToolErrorCode

DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")


def test_handler_passes_query_and_limit_to_service() -> None:
    service = create_autospec(BookService, instance=True)
    service.search_catalog.return_value = CatalogSearchResult(
        books=(),
        source=CatalogSource.LOCAL,
    )
    handler = SearchBooksHandler(service)
    arguments = SearchBooksArguments(query="Дюна", limit=5)

    result = handler(arguments)

    service.search_catalog.assert_called_once_with(query="Дюна", limit=5)
    assert result == SearchBooksResult(books=[])


def test_handler_converts_domain_book_to_tool_result() -> None:
    service = create_autospec(BookService, instance=True)
    service.search_catalog.return_value = CatalogSearchResult(
        books=(
            CatalogBook(
                id=DUNE_ID,
                title="Дюна",
                author="Фрэнк Герберт",
                tags=("politics", "science_fiction", "space_opera"),
            ),
        ),
        source=CatalogSource.OPEN_LIBRARY,
        cached=True,
    )
    handler = SearchBooksHandler(service)

    result = handler(SearchBooksArguments(query="Дюна"))

    assert result == SearchBooksResult(
        books=[
            BookToolResult(
                id=DUNE_ID,
                title="Дюна",
                author="Фрэнк Герберт",
                tags=["politics", "science_fiction", "space_opera"],
            )
        ],
        source=CatalogSource.OPEN_LIBRARY,
        cached=True,
    )


def test_handler_searches_seeded_database_and_returns_empty_result(
    session: Session,
) -> None:
    handler = SearchBooksHandler(BookService(BookRepository(session)))

    found = handler(SearchBooksArguments(query="дюна"))
    missing = handler(SearchBooksArguments(query="несуществующая книга"))

    assert [book.title for book in found.books] == ["Дюна"]
    assert found.books[0].tags == [
        "politics",
        "science_fiction",
        "space_opera",
    ]
    assert missing == SearchBooksResult(books=[])


def test_handler_converts_catalog_failure_to_safe_tool_error() -> None:
    service = create_autospec(BookService, instance=True)
    service.search_catalog.side_effect = CatalogUnavailableError("secret URL")

    with pytest.raises(ToolExecutionError) as raised:
        SearchBooksHandler(service)(SearchBooksArguments(query="Дюна"))

    assert raised.value.code is ToolErrorCode.CATALOG_UNAVAILABLE
    assert raised.value.message == "Book catalog is unavailable"
