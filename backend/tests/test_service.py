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
