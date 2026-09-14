from collections.abc import Generator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
import httpx
from openai import OpenAI
from sqlalchemy.orm import Session

from app.catalog.local import LocalBookCatalog
from app.catalog.open_library import HttpOpenLibraryTransport, OpenLibraryCatalog
from app.catalog.provider import BookCatalog
from app.catalog.resilient import ResilientBookCatalog, TTLSearchCache
from app.agent.repository import AgentRunRepository
from app.agent.approval import ApprovalService
from app.agent.service import AgentService
from app.config import Settings, get_settings
from app.db import get_db
from app.llm.deepseek import DeepSeekProvider
from app.llm.exceptions import LLMNotConfiguredError
from app.llm.provider import LLMProvider
from app.llm.service import ChatService
from app.memory.repository import MemoryRepository
from app.memory.service import MemoryService
from app.repository import BookRepository
from app.service import BookService
from app.tools.books import SEARCH_BOOKS_TOOL, SearchBooksHandler
from app.tools.library import (
    ADD_BOOK_TOOL,
    GET_USER_LIBRARY_TOOL,
    REMOVE_BOOK_TOOL,
    UPDATE_BOOK_STATUS_TOOL,
    AddBookHandler,
    GetUserLibraryHandler,
    RemoveBookApprovalSummary,
    RemoveBookHandler,
    UpdateBookStatusHandler,
)
from app.tools.memory import (
    SEARCH_USER_NOTES_TOOL,
    SearchUserNotesHandler,
)
from app.tools.recommendations import (
    FIND_SIMILAR_BOOKS_TOOL,
    FindSimilarBooksHandler,
)
from app.tools.registry import ToolRegistry


@lru_cache
def _get_catalog_cache(ttl_seconds: float, max_entries: int) -> TTLSearchCache:
    return TTLSearchCache(ttl_seconds=ttl_seconds, max_entries=max_entries)


def get_book_catalog(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Generator[BookCatalog, None, None]:
    local_catalog = LocalBookCatalog(BookRepository(db))
    if settings.catalog_provider == "local":
        yield local_catalog
        return

    with httpx.Client(timeout=settings.open_library_timeout_seconds) as client:
        primary = OpenLibraryCatalog(
            HttpOpenLibraryTransport(
                client,
                base_url=settings.open_library_base_url,
                user_agent=settings.open_library_user_agent,
            )
        )
        yield ResilientBookCatalog(
            primary,
            local_catalog,
            _get_catalog_cache(
                settings.catalog_cache_ttl_seconds,
                settings.catalog_cache_max_entries,
            ),
            max_retries=settings.open_library_max_retries,
            retry_delay_seconds=settings.open_library_retry_delay_seconds,
        )


def get_book_service(
    db: Annotated[Session, Depends(get_db)],
    catalog: Annotated[BookCatalog, Depends(get_book_catalog)],
) -> BookService:
    return BookService(BookRepository(db), catalog)


def get_memory_service(
    db: Annotated[Session, Depends(get_db)],
) -> MemoryService:
    return MemoryService(MemoryRepository(db))


def get_llm_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LLMProvider:
    if (
        settings.deepseek_api_key is None
        or not settings.deepseek_api_key.get_secret_value()
    ):
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


def get_tool_registry(
    service: Annotated[BookService, Depends(get_book_service)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, SearchBooksHandler(service))
    registry.register(
        FIND_SIMILAR_BOOKS_TOOL,
        FindSimilarBooksHandler(service, settings.demo_user_id),
    )
    registry.register(
        GET_USER_LIBRARY_TOOL,
        GetUserLibraryHandler(service, settings.demo_user_id),
    )
    registry.register(
        ADD_BOOK_TOOL,
        AddBookHandler(service, settings.demo_user_id),
    )
    registry.register(
        UPDATE_BOOK_STATUS_TOOL,
        UpdateBookStatusHandler(service, settings.demo_user_id),
    )
    registry.register(
        SEARCH_USER_NOTES_TOOL,
        SearchUserNotesHandler(memory_service, settings.demo_user_id),
    )
    registry.register(
        REMOVE_BOOK_TOOL,
        RemoveBookHandler(service, settings.demo_user_id, commit=False),
        approval_summary=RemoveBookApprovalSummary(
            service,
            settings.demo_user_id,
        ),
    )
    return registry


def get_agent_repository(
    db: Annotated[Session, Depends(get_db)],
) -> AgentRunRepository:
    return AgentRunRepository(db)


def get_agent_service(
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    registry: Annotated[ToolRegistry, Depends(get_tool_registry)],
    repository: Annotated[AgentRunRepository, Depends(get_agent_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentService:
    return AgentService(
        provider,
        registry,
        repository,
        max_steps=settings.agent_max_steps,
        approval_ttl_seconds=settings.pending_action_ttl_seconds,
        history_max_tool_rounds=settings.agent_history_max_tool_rounds,
        provider_name="deepseek",
        model_name=settings.deepseek_model,
    )


def get_approval_service(
    registry: Annotated[ToolRegistry, Depends(get_tool_registry)],
    repository: Annotated[AgentRunRepository, Depends(get_agent_repository)],
) -> ApprovalService:
    return ApprovalService(registry, repository)
