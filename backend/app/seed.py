from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Book

SEED_BOOKS = (
    (
        "10000000-0000-0000-0000-000000000001",
        "Дюна",
        "Фрэнк Герберт",
        ("politics", "science_fiction", "space_opera"),
    ),
    (
        "10000000-0000-0000-0000-000000000002",
        "1984",
        "Джордж Оруэлл",
        ("classic", "dystopia", "politics"),
    ),
    (
        "10000000-0000-0000-0000-000000000003",
        "Марсианин",
        "Энди Вейер",
        ("science_fiction", "space", "survival"),
    ),
    (
        "10000000-0000-0000-0000-000000000004",
        "Atomic Habits",
        "James Clear",
        ("nonfiction", "productivity", "psychology"),
    ),
    (
        "10000000-0000-0000-0000-000000000005",
        "Солярис",
        "Станислав Лем",
        ("first_contact", "philosophy", "science_fiction"),
    ),
    (
        "10000000-0000-0000-0000-000000000006",
        "Пикник на обочине",
        "Аркадий и Борис Стругацкие",
        ("dystopia", "first_contact", "science_fiction"),
    ),
    (
        "10000000-0000-0000-0000-000000000007",
        "Цветы для Элджернона",
        "Дэниел Киз",
        ("classic", "psychology", "science_fiction"),
    ),
    (
        "10000000-0000-0000-0000-000000000008",
        "Левая рука Тьмы",
        "Урсула Ле Гуин",
        ("politics", "science_fiction", "sociology"),
    ),
    (
        "10000000-0000-0000-0000-000000000009",
        "Нейромант",
        "Уильям Гибсон",
        ("cyberpunk", "dystopia", "science_fiction"),
    ),
    (
        "10000000-0000-0000-0000-000000000010",
        "Sapiens",
        "Yuval Noah Harari",
        ("history", "nonfiction", "sociology"),
    ),
)


def seed_database(session: Session) -> int:
    existing_books = {book.id: book for book in session.scalars(select(Book))}
    added = 0

    for book_id, title, author, tags in SEED_BOOKS:
        parsed_id = UUID(book_id)
        book = existing_books.get(parsed_id)
        if book is None:
            session.add(
                Book(
                    id=parsed_id,
                    title=title,
                    author=author,
                    tags=list(tags),
                )
            )
            added += 1
            continue

        book.title = title
        book.author = author
        book.tags = list(tags)

    session.commit()
    return added


def main() -> None:
    with SessionLocal() as session:
        added = seed_database(session)
        total = session.scalar(select(func.count()).select_from(Book))
    print(f"Seed complete: added={added}, total={total}")


if __name__ == "__main__":
    main()
