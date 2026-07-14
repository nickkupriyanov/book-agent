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
