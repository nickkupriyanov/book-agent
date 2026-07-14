from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Book

SEED_BOOKS = (
    ("10000000-0000-0000-0000-000000000001", "Дюна", "Фрэнк Герберт"),
    ("10000000-0000-0000-0000-000000000002", "1984", "Джордж Оруэлл"),
    ("10000000-0000-0000-0000-000000000003", "Марсианин", "Энди Вейер"),
    ("10000000-0000-0000-0000-000000000004", "Atomic Habits", "James Clear"),
    ("10000000-0000-0000-0000-000000000005", "Солярис", "Станислав Лем"),
    ("10000000-0000-0000-0000-000000000006", "Пикник на обочине", "Аркадий и Борис Стругацкие"),
    ("10000000-0000-0000-0000-000000000007", "Цветы для Элджернона", "Дэниел Киз"),
    ("10000000-0000-0000-0000-000000000008", "Левая рука Тьмы", "Урсула Ле Гуин"),
    ("10000000-0000-0000-0000-000000000009", "Нейромант", "Уильям Гибсон"),
    ("10000000-0000-0000-0000-000000000010", "Sapiens", "Yuval Noah Harari"),
)


def seed_database(session: Session) -> int:
    existing_ids = set(session.scalars(select(Book.id)))
    new_books = [
        Book(id=UUID(book_id), title=title, author=author)
        for book_id, title, author in SEED_BOOKS
        if UUID(book_id) not in existing_ids
    ]
    session.add_all(new_books)
    session.commit()
    return len(new_books)


def main() -> None:
    with SessionLocal() as session:
        added = seed_database(session)
        total = session.scalar(select(func.count()).select_from(Book))
    print(f"Seed complete: added={added}, total={total}")


if __name__ == "__main__":
    main()
