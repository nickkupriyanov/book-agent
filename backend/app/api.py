from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import ReadingStatus
from app.repository import BookRepository
from app.schemas import (
    BookResponse,
    LibraryEntryCreate,
    LibraryEntryResponse,
    LibraryStatusUpdate,
)
from app.service import BookService

router = APIRouter(prefix="/api")


def get_book_service(db: Annotated[Session, Depends(get_db)]) -> BookService:
    return BookService(BookRepository(db))


@router.get("/books/search", response_model=list[BookResponse])
def search_books(
    service: Annotated[BookService, Depends(get_book_service)],
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[BookResponse]:
    return service.search_books(query=q, limit=limit)


@router.get("/library", response_model=list[LibraryEntryResponse])
def get_library(
    service: Annotated[BookService, Depends(get_book_service)],
    status_filter: Annotated[ReadingStatus | None, Query(alias="status")] = None,
) -> list[LibraryEntryResponse]:
    return service.get_library(get_settings().demo_user_id, status_filter)


@router.post(
    "/library",
    response_model=LibraryEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_library_entry(
    payload: LibraryEntryCreate,
    service: Annotated[BookService, Depends(get_book_service)],
) -> LibraryEntryResponse:
    return service.add_book(
        user_id=get_settings().demo_user_id,
        book_id=payload.book_id,
        status=payload.status,
    )


@router.patch(
    "/library/{book_id}/status",
    response_model=LibraryEntryResponse,
)
def update_library_status(
    book_id: UUID,
    payload: LibraryStatusUpdate,
    service: Annotated[BookService, Depends(get_book_service)],
) -> LibraryEntryResponse:
    return service.update_status(
        user_id=get_settings().demo_user_id,
        book_id=book_id,
        status=payload.status,
    )
