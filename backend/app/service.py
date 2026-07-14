from uuid import UUID

from app.exceptions import (
    BookNotFoundError,
    DuplicateLibraryEntryError,
    LibraryEntryNotFoundError,
)
from app.models import Book, LibraryEntry, ReadingStatus
from app.repository import BookRepository


class BookService:
    def __init__(self, repository: BookRepository) -> None:
        self.repository = repository

    def search_books(self, query: str, limit: int = 20) -> list[Book]:
        return self.repository.search_books(query=query, limit=limit)

    def get_library(
        self, user_id: UUID, status: ReadingStatus | None = None
    ) -> list[LibraryEntry]:
        return self.repository.list_library(user_id=user_id, status=status)

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
