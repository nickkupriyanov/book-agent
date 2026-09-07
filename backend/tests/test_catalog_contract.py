from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.catalog.local import LocalBookCatalog
from app.catalog.models import CatalogSource
from app.repository import BookRepository

DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")


def test_local_catalog_satisfies_search_contract(session: Session) -> None:
    catalog = LocalBookCatalog(BookRepository(session))

    result = catalog.search_books("дЮн", limit=5)

    assert result.source is CatalogSource.LOCAL
    assert result.degraded is False
    assert result.cached is False
    assert [book.id for book in result.books] == [DUNE_ID]
    assert result.books[0].title == "Дюна"


@pytest.mark.parametrize(("query", "limit"), [("", 1), ("   ", 1), ("Dune", 0)])
def test_local_catalog_rejects_invalid_search(
    session: Session,
    query: str,
    limit: int,
) -> None:
    catalog = LocalBookCatalog(BookRepository(session))

    with pytest.raises(ValueError):
        catalog.search_books(query, limit)
