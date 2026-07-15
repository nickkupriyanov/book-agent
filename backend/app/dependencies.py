from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.llm.provider import LLMProvider
from app.llm.service import ChatService
from app.repository import BookRepository
from app.service import BookService


def get_book_service(db: Annotated[Session, Depends(get_db)]) -> BookService:
    return BookService(BookRepository(db))


def get_llm_provider() -> LLMProvider:
    raise RuntimeError("LLM provider is not configured")


def get_chat_service(
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> ChatService:
    return ChatService(provider)
