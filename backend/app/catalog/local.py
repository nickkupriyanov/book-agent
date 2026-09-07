from app.catalog.models import CatalogBook, CatalogSearchResult, CatalogSource
from app.repository import BookRepository


class LocalBookCatalog:
    def __init__(self, repository: BookRepository) -> None:
        self._repository = repository

    def search_books(self, query: str, limit: int) -> CatalogSearchResult:
        if not query.strip():
            raise ValueError("query must not be blank")
        if limit < 1:
            raise ValueError("limit must be at least 1")

        books = self._repository.search_books(query=query, limit=limit)
        return CatalogSearchResult(
            books=tuple(
                CatalogBook(
                    id=book.id,
                    title=book.title,
                    author=book.author,
                    tags=tuple(book.tags),
                )
                for book in books
            ),
            source=CatalogSource.LOCAL,
        )
