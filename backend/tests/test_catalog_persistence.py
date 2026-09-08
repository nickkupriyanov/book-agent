from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.catalog.models import CatalogBook, CatalogSearchResult, CatalogSource
from app.models import Base, Book, ReadingStatus
from app.repository import BookRepository
from app.service import BookService

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
WORK_ID = "OL123W"


class StaticExternalCatalog:
    def __init__(self, book: CatalogBook, barrier: Barrier | None = None) -> None:
        self._book = book
        self._barrier = barrier

    def search_books(self, query: str, limit: int) -> CatalogSearchResult:
        if self._barrier is not None:
            self._barrier.wait(timeout=5)
        return CatalogSearchResult(
            books=(self._book,),
            source=CatalogSource.OPEN_LIBRARY,
        )


def external_book(*, title: str = "A Book") -> CatalogBook:
    return CatalogBook(
        id=uuid5(NAMESPACE_URL, f"https://openlibrary.org/works/{WORK_ID}"),
        title=title,
        author="Ada Author",
        tags=("fiction",),
        catalog_source=CatalogSource.OPEN_LIBRARY,
        external_id=WORK_ID,
        isbn="9780306406157",
    )


def test_external_search_persists_before_existing_add_book_flow(
    session: Session,
) -> None:
    book = external_book()
    service = BookService(BookRepository(session), StaticExternalCatalog(book))

    first = service.search_catalog("A Book", 5)
    second = service.search_catalog("A Book", 5)
    entry = service.add_book(
        user_id=USER_ID,
        book_id=book.id,
        status=ReadingStatus.WANT_TO_READ,
    )

    assert first.books[0].id == second.books[0].id == book.id
    assert session.scalar(
        select(func.count()).select_from(Book).where(Book.id == book.id)
    ) == 1
    assert entry.book_id == book.id


def test_repeated_external_result_refreshes_metadata_without_new_row(
    session: Session,
) -> None:
    repository = BookRepository(session)
    first = repository.upsert_catalog_books((external_book(title="Old title"),))[0]
    second = repository.upsert_catalog_books((external_book(title="New title"),))[0]

    assert first.id == second.id
    assert second.title == "New title"
    assert session.scalar(select(func.count()).select_from(Book)) == 11


def test_unique_external_identity_rejects_a_different_internal_id(
    session: Session,
) -> None:
    repository = BookRepository(session)
    repository.upsert_catalog_books((external_book(),))
    session.add(
        Book(
            id=uuid4(),
            title="Conflicting identity",
            author="Other",
            tags=[],
            catalog_source="open_library",
            external_id=WORK_ID,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_concurrent_external_searches_keep_one_catalog_row(tmp_path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'catalog-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = Barrier(2)
    book = external_book()

    def search() -> str:
        with sessions() as session:
            service = BookService(
                BookRepository(session),
                StaticExternalCatalog(book, barrier),
            )
            return str(service.search_catalog("A Book", 5).books[0].id)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            ids = list(executor.map(lambda _: search(), range(2)))
        with sessions() as session:
            count = session.scalar(
                select(func.count()).select_from(Book).where(Book.id == book.id)
            )
        assert ids == [str(book.id), str(book.id)]
        assert count == 1
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
