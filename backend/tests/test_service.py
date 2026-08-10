from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.exceptions import (
    BookNotFoundError,
    DuplicateLibraryEntryError,
    LibraryEntryNotFoundError,
)
from app.models import ReadingStatus
from app.repository import BookRepository
from app.service import BookService

DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")


def test_service_returns_book_by_id(session: Session) -> None:
    service = BookService(BookRepository(session))

    book = service.get_book(DUNE_ID)

    assert book.title == "Дюна"


def test_service_rejects_unknown_book_id(session: Session) -> None:
    service = BookService(BookRepository(session))

    with pytest.raises(BookNotFoundError):
        service.get_book(uuid4())


def test_service_rejects_duplicate(session: Session) -> None:
    service = BookService(BookRepository(session))
    user_id = get_settings().demo_user_id

    service.add_book(user_id, DUNE_ID, ReadingStatus.WANT_TO_READ)

    with pytest.raises(DuplicateLibraryEntryError):
        service.add_book(user_id, DUNE_ID, ReadingStatus.READING)


def test_service_updates_status(session: Session) -> None:
    service = BookService(BookRepository(session))
    user_id = get_settings().demo_user_id
    service.add_book(user_id, DUNE_ID, ReadingStatus.READING)

    entry = service.update_status(user_id, DUNE_ID, ReadingStatus.FINISHED)

    assert entry.status is ReadingStatus.FINISHED


def test_service_rejects_update_for_missing_entry(session: Session) -> None:
    service = BookService(BookRepository(session))

    with pytest.raises(LibraryEntryNotFoundError):
        service.update_status(
            get_settings().demo_user_id,
            DUNE_ID,
            ReadingStatus.FINISHED,
        )


def test_service_removes_own_library_entry_without_removing_catalog_book(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    user_id = get_settings().demo_user_id
    service.add_book(user_id, DUNE_ID, ReadingStatus.READING)

    removed = service.remove_book(user_id, DUNE_ID)

    assert removed.book_id == DUNE_ID
    assert removed.status is ReadingStatus.READING
    assert service.get_library(user_id) == []
    assert service.get_book(DUNE_ID).title == "Дюна"


def test_service_rejects_removing_missing_or_another_users_entry(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    user_id = get_settings().demo_user_id
    other_user_id = uuid4()

    with pytest.raises(LibraryEntryNotFoundError):
        service.remove_book(user_id, DUNE_ID)

    service.add_book(other_user_id, DUNE_ID, ReadingStatus.WANT_TO_READ)

    with pytest.raises(LibraryEntryNotFoundError):
        service.remove_book(user_id, DUNE_ID)

    assert len(service.get_library(other_user_id)) == 1
