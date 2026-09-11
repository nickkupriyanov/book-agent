from typing import NoReturn
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.agent.repository import AgentRunRepository
from app.agent.service import AgentService
from app.catalog.local import LocalBookCatalog
from app.catalog.resilient import ResilientBookCatalog, TTLSearchCache
from app.llm.fake import FakeLLMProvider
from app.llm.models import ModelResponse
from app.repository import BookRepository
from app.schemas import AgentRunResponse
from app.service import BookService
from app.tools.books import SEARCH_BOOKS_TOOL, SearchBooksHandler
from app.tools.models import ToolCall
from app.tools.registry import ToolRegistry

USER_ID = UUID("00000000-0000-0000-0000-000000000001")


class TimeoutCatalog:
    def __init__(self) -> None:
        self.calls = 0

    def search_books(self, query: str, limit: int) -> NoReturn:
        self.calls += 1
        raise httpx.ReadTimeout(
            "timed out",
            request=httpx.Request("GET", "https://catalog.example"),
        )


def test_timeout_retries_then_exposes_local_fallback_in_agent_trace(
    session: Session,
) -> None:
    repository = BookRepository(session)
    primary = TimeoutCatalog()
    catalog = ResilientBookCatalog(
        primary,
        LocalBookCatalog(repository),
        TTLSearchCache(ttl_seconds=10, max_entries=2),
        max_retries=1,
        sleeper=lambda _: None,
    )
    service = BookService(repository, catalog)
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, SearchBooksHandler(service))
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="stage8-search-1",
                        name="search_books",
                        arguments={"query": "Дюна", "limit": 5},
                    )
                ],
            ),
            ModelResponse(text="Нашёл результат в резервном каталоге."),
        ]
    )

    run = AgentService(
        provider,
        registry,
        AgentRunRepository(session),
    ).run(USER_ID, "Найди Дюну")
    response = AgentRunResponse.model_validate(run)

    assert primary.calls == 2
    assert response.status.value == "completed"
    assert response.steps[0].catalog_searches[0].model_dump(mode="json") == {
        "source": "local",
        "degraded": True,
        "cached": False,
    }
