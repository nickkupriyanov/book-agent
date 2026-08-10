from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import Book, LibraryEntry, ReadingStatus


class BookRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def search_books(self, query: str, limit: int) -> list[Book]:
        books = self.session.scalars(select(Book).order_by(Book.title))
        normalized_query = query.casefold()
        return [book for book in books if normalized_query in book.title.casefold()][:limit]

    def list_books(self) -> list[Book]:
        return list(self.session.scalars(select(Book).order_by(Book.id)))

    def get_book(self, book_id: UUID) -> Book | None:
        return self.session.get(Book, book_id)

    def get_library_entry(self, user_id: UUID, book_id: UUID) -> LibraryEntry | None:
        return self.session.get(LibraryEntry, (user_id, book_id))

    def list_library(
        self,
        user_id: UUID,
        status: ReadingStatus | None = None,
        *,
        limit: int | None = None,
        recent_first: bool = False,
    ) -> list[LibraryEntry]:
        statement: Select[tuple[LibraryEntry]] = select(LibraryEntry).where(
            LibraryEntry.user_id == user_id
        )
        if status is not None:
            statement = statement.where(LibraryEntry.status == status)
        if recent_first:
            statement = statement.order_by(
                LibraryEntry.updated_at.desc(),
                LibraryEntry.book_id,
            )
        else:
            statement = statement.order_by(
                LibraryEntry.created_at,
                LibraryEntry.book_id,
            )
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def add_library_entry(self, entry: LibraryEntry) -> LibraryEntry:
        self.session.add(entry)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def save_library_entry(self, entry: LibraryEntry) -> LibraryEntry:
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def delete_library_entry(
        self,
        user_id: UUID,
        book_id: UUID,
    ) -> LibraryEntry | None:
        entry = self.get_library_entry(user_id, book_id)
        if entry is None:
            return None

        self.session.delete(entry)
        self.session.commit()
        return entry
