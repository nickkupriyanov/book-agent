from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.repository import BookRepository
from app.service import BookService


def get_book_service(db: Annotated[Session, Depends(get_db)]) -> BookService:
    return BookService(BookRepository(db))
