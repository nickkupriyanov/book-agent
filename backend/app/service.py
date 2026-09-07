from dataclasses import dataclass
from uuid import UUID

from app.catalog.local import LocalBookCatalog
from app.catalog.models import CatalogBook, CatalogSearchResult
from app.catalog.provider import BookCatalog
from app.exceptions import (
    BookNotFoundError,
    DuplicateLibraryEntryError,
    LibraryEntryNotFoundError,
)
from app.models import Book, LibraryEntry, ReadingStatus
from app.repository import BookRepository


@dataclass(frozen=True)
class RecommendationCandidate:
    book: Book
    matched_tags: tuple[str, ...]
    score: int


class BookService:
    def __init__(
        self,
        repository: BookRepository,
        catalog: BookCatalog | None = None,
    ) -> None:
        self.repository = repository
        self.catalog = catalog or LocalBookCatalog(repository)

    def search_catalog(self, query: str, limit: int = 20) -> CatalogSearchResult:
        return self.catalog.search_books(query=query, limit=limit)

    def search_books(self, query: str, limit: int = 20) -> list[CatalogBook]:
        return list(self.search_catalog(query=query, limit=limit).books)

    def get_book(self, book_id: UUID) -> Book:
        book = self.repository.get_book(book_id)
        if book is None:
            raise BookNotFoundError(book_id)
        return book

    def get_library(
        self,
        user_id: UUID,
        status: ReadingStatus | None = None,
        *,
        limit: int | None = None,
        recent_first: bool = False,
    ) -> list[LibraryEntry]:
        return self.repository.list_library(
            user_id=user_id,
            status=status,
            limit=limit,
            recent_first=recent_first,
        )

    def get_library_entry(
        self,
        user_id: UUID,
        book_id: UUID,
    ) -> LibraryEntry:
        entry = self.repository.get_library_entry(user_id, book_id)
        if entry is None:
            raise LibraryEntryNotFoundError(book_id)
        return entry

    def find_similar_books(
        self,
        user_id: UUID,
        source_book_ids: list[UUID],
        limit: int = 3,
    ) -> list[RecommendationCandidate]:
        if not source_book_ids:
            raise ValueError("source_book_ids must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least 1")

        source_ids = set(source_book_ids)
        source_books = [
            self.get_book(book_id)
            for book_id in sorted(source_ids, key=str)
        ]
        source_tags = {
            tag
            for source_book in source_books
            for tag in source_book.tags
        }
        library_book_ids = {
            entry.book_id for entry in self.get_library(user_id)
        }
        excluded_ids = source_ids | library_book_ids
        candidates_by_id: dict[UUID, RecommendationCandidate] = {}

        for book in self.repository.list_books():
            if book.id in excluded_ids or book.id in candidates_by_id:
                continue

            matched_tags = tuple(sorted(source_tags.intersection(book.tags)))
            if not matched_tags:
                continue

            candidates_by_id[book.id] = RecommendationCandidate(
                book=book,
                matched_tags=matched_tags,
                score=len(matched_tags),
            )

        candidates = sorted(
            candidates_by_id.values(),
            key=lambda candidate: (-candidate.score, str(candidate.book.id)),
        )
        return candidates[:limit]

    def add_book(
        self, user_id: UUID, book_id: UUID, status: ReadingStatus
    ) -> LibraryEntry:
        if self.repository.get_book(book_id) is None:
            raise BookNotFoundError(book_id)
        if self.repository.get_library_entry(user_id, book_id) is not None:
            raise DuplicateLibraryEntryError(book_id)

        return self.repository.add_library_entry(
            LibraryEntry(user_id=user_id, book_id=book_id, status=status)
        )

    def update_status(
        self, user_id: UUID, book_id: UUID, status: ReadingStatus
    ) -> LibraryEntry:
        entry = self.repository.get_library_entry(user_id, book_id)
        if entry is None:
            raise LibraryEntryNotFoundError(book_id)

        entry.status = status
        return self.repository.save_library_entry(entry)

    def remove_book(
        self,
        user_id: UUID,
        book_id: UUID,
        *,
        commit: bool = True,
    ) -> LibraryEntry:
        if commit:
            entry = self.repository.delete_library_entry(user_id, book_id)
        else:
            entry = self.repository.delete_library_entry(
                user_id,
                book_id,
                commit=False,
            )
        if entry is None:
            raise LibraryEntryNotFoundError(book_id)
        return entry
