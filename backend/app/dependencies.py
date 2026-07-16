from typing import Annotated

from fastapi import Depends
from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.llm.deepseek import DeepSeekProvider
from app.llm.exceptions import LLMNotConfiguredError
from app.llm.provider import LLMProvider
from app.llm.service import ChatService
from app.repository import BookRepository
from app.service import BookService


def get_book_service(db: Annotated[Session, Depends(get_db)]) -> BookService:
    return BookService(BookRepository(db))


def get_llm_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LLMProvider:
    if settings.deepseek_api_key is None:
        raise LLMNotConfiguredError("LLM provider is not configured")

    client = OpenAI(
        api_key=settings.deepseek_api_key.get_secret_value(),
        base_url=settings.deepseek_base_url,
        timeout=settings.deepseek_timeout_seconds,
        max_retries=0,
    )
    return DeepSeekProvider(client=client, model=settings.deepseek_model)


def get_chat_service(
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> ChatService:
    return ChatService(provider)
