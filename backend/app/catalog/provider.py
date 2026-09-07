from typing import Protocol

from app.catalog.models import CatalogSearchResult


class BookCatalog(Protocol):
    def search_books(self, query: str, limit: int) -> CatalogSearchResult: ...
