from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import Book, LibraryEntry, ReadingStatus

if TYPE_CHECKING:
    from app.catalog.models import CatalogBook


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

    def upsert_catalog_books(
        self,
        books: tuple["CatalogBook", ...],
    ) -> list[Book]:
        if not books:
            return []

        updated_at = datetime.now(timezone.utc)
        rows = [
            {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "tags": list(book.tags),
                "catalog_source": book.catalog_source.value,
                "external_id": book.external_id,
                "isbn": book.isbn,
                "cover_url": book.cover_url,
                "catalog_updated_at": updated_at,
            }
            for book in books
        ]
        update_columns = (
            "title",
            "author",
            "tags",
            "isbn",
            "cover_url",
            "catalog_updated_at",
        )
        dialect_name = self.session.get_bind().dialect.name
        insert_factory = {
            "sqlite": sqlite_insert,
            "postgresql": postgresql_insert,
        }.get(dialect_name)
        if insert_factory is not None:
            statement = insert_factory(Book).values(rows)
            statement = statement.on_conflict_do_update(
                index_elements=[Book.id],
                set_={
                    name: getattr(statement.excluded, name)
                    for name in update_columns
                },
            )
            self.session.execute(statement)
        else:
            for row in rows:
                self.session.merge(Book(**row))

        self.session.commit()
        self.session.expire_all()
        persisted_by_id = {
            book.id: book
            for book in self.session.scalars(
                select(Book).where(Book.id.in_([book.id for book in books]))
            )
        }
        return [persisted_by_id[book.id] for book in books]

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
        *,
        commit: bool = True,
    ) -> LibraryEntry | None:
        entry = self.get_library_entry(user_id, book_id)
        if entry is None:
            return None

        self.session.delete(entry)
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return entry
