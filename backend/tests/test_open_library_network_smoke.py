import os

import httpx
import pytest

from app.catalog.models import CatalogSource
from app.catalog.open_library import HttpOpenLibraryTransport, OpenLibraryCatalog
from app.config import get_settings


@pytest.mark.network
@pytest.mark.skipif(
    os.getenv("RUN_OPEN_LIBRARY_SMOKE") != "1",
    reason="set RUN_OPEN_LIBRARY_SMOKE=1 to call Open Library",
)
def test_real_open_library_search_smoke() -> None:
    settings = get_settings()
    with httpx.Client(timeout=settings.open_library_timeout_seconds) as client:
        catalog = OpenLibraryCatalog(
            HttpOpenLibraryTransport(
                client,
                base_url=settings.open_library_base_url,
                user_agent=settings.open_library_user_agent,
            )
        )
        result = catalog.search_books("Dune Frank Herbert", 3)

    assert result.source is CatalogSource.OPEN_LIBRARY
    assert result.books
    assert all(book.external_id is not None for book in result.books)
