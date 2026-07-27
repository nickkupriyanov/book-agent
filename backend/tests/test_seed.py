from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Book
from app.seed import SEED_BOOKS, seed_database


def test_seed_is_idempotent(session: Session) -> None:
    initial_count = session.scalar(select(func.count()).select_from(Book))

    added = seed_database(session)
    final_count = session.scalar(select(func.count()).select_from(Book))

    assert initial_count == len(SEED_BOOKS)
    assert added == 0
    assert final_count == initial_count


def test_seed_restores_known_book_metadata(session: Session) -> None:
    dune_id = UUID("10000000-0000-0000-0000-000000000001")
    dune = session.get(Book, dune_id)
    assert dune is not None
    dune.title = "Changed title"
    dune.author = "Changed author"
    dune.tags = ["duplicate", "duplicate"]
    session.commit()

    added = seed_database(session)
    session.refresh(dune)

    assert added == 0
    assert dune.title == "Дюна"
    assert dune.author == "Фрэнк Герберт"
    assert dune.tags == ["politics", "science_fiction", "space_opera"]


def test_seed_tags_are_non_empty_normalized_and_unique(session: Session) -> None:
    books = list(session.scalars(select(Book)))

    for book in books:
        assert book.tags
        assert book.tags == sorted(set(book.tags))
        assert all(tag == tag.strip().casefold() for tag in book.tags)
