import json
from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.repository import AgentRunRepository
from app.agent.service import AgentService
from app.llm.fake import FakeLLMProvider
from app.llm.exceptions import LLMTimeoutError
from app.llm.models import MessageRole, ModelResponse
from app.models import AgentRun, AgentRunStatus, ReadingStatus
from app.repository import BookRepository
from app.service import BookService
from app.tools.books import (
    SEARCH_BOOKS_TOOL,
    SearchBooksHandler,
    SearchBooksResult,
)
from app.tools.library import ADD_BOOK_TOOL, AddBookHandler
from app.tools.models import ToolCall
from app.tools.registry import ToolRegistry

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")


def test_agent_runs_two_tools_and_returns_final_answer(session: Session) -> None:
    book_service = BookService(BookRepository(session))
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, SearchBooksHandler(book_service))
    registry.register(ADD_BOOK_TOOL, AddBookHandler(book_service, USER_ID))
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="search-1",
                        name="search_books",
                        arguments={"query": "Дюна", "limit": 5},
                    )
                ],
            ),
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="add-1",
                        name="add_book",
                        arguments={
                            "book_id": str(DUNE_ID),
                            "status": "want_to_read",
                        },
                    )
                ],
            ),
            ModelResponse(text="Добавил «Дюну» в список на чтение."),
        ]
    )
    agent = AgentService(
        provider,
        registry,
        AgentRunRepository(session),
    )

    run = agent.run(USER_ID, "Найди Дюну и добавь в список на чтение")

    assert run.status is AgentRunStatus.COMPLETED
    assert run.final_answer == "Добавил «Дюну» в список на чтение."
    assert run.stop_reason == "final_response"
    assert [step.step_number for step in run.steps] == [1, 2, 3]
    assert run.steps[0].response["tool_calls"][0]["id"] == "search-1"
    assert run.steps[0].tool_results[0]["tool_call_id"] == "search-1"
    assert run.steps[1].response["tool_calls"][0]["id"] == "add-1"
    assert run.steps[1].tool_results[0]["tool_call_id"] == "add-1"
    assert run.steps[2].tool_results == []

    library = book_service.get_library(USER_ID)
    assert len(library) == 1
    assert library[0].book.id == DUNE_ID
    assert library[0].status is ReadingStatus.WANT_TO_READ

    assert len(provider.calls) == 3
    assert provider.calls[1][-1].role is MessageRole.TOOL
    assert provider.calls[1][-1].tool_call_id == "search-1"
    assert json.loads(provider.calls[1][-1].content)["tool_call_id"] == "search-1"
    assert provider.calls[2][-1].tool_call_id == "add-1"
    assert [definition.name for definition in provider.tools_by_call[0]] == [
        "search_books",
        "add_book",
    ]


def test_agent_returns_all_tool_results_before_next_model_call(
    session: Session,
) -> None:
    book_service = BookService(BookRepository(session))
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, SearchBooksHandler(book_service))
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="search-1",
                        name="search_books",
                        arguments={"query": "Дюна"},
                    ),
                    ToolCall(
                        id="search-2",
                        name="search_books",
                        arguments={"query": "1984"},
                    ),
                ],
            ),
            ModelResponse(text="Нашёл обе книги."),
        ]
    )
    agent = AgentService(
        provider,
        registry,
        AgentRunRepository(session),
    )

    run = agent.run(USER_ID, "Найди Дюну и 1984")

    assert run.status is AgentRunStatus.COMPLETED
    assert len(run.steps[0].tool_results) == 2
    assert [message.tool_call_id for message in provider.calls[1][-2:]] == [
        "search-1",
        "search-2",
    ]


def test_agent_stops_after_maximum_model_calls(session: Session) -> None:
    book_service = BookService(BookRepository(session))
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, SearchBooksHandler(book_service))
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="search-1",
                        name="search_books",
                        arguments={"query": "Дюна"},
                    )
                ],
            ),
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="search-2",
                        name="search_books",
                        arguments={"query": "1984"},
                    )
                ],
            ),
        ]
    )
    agent = AgentService(
        provider,
        registry,
        AgentRunRepository(session),
        max_steps=2,
    )

    run = agent.run(USER_ID, "Продолжай искать книги")

    assert run.status is AgentRunStatus.STEP_LIMIT_EXCEEDED
    assert run.stop_reason == "max_steps"
    assert len(run.steps) == 2
    assert len(provider.calls) == 2


def test_agent_stops_before_repeating_same_tool_call(session: Session) -> None:
    handler = Mock(return_value=SearchBooksResult(books=[]))
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, handler)
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="search-1",
                        name="search_books",
                        arguments={"query": "Дюна", "limit": 5},
                    )
                ],
            ),
            ModelResponse(
                text="Попробую ещё раз",
                tool_calls=[
                    ToolCall(
                        id="search-2",
                        name="search_books",
                        arguments={"limit": 5, "query": "Дюна"},
                    )
                ],
            ),
        ]
    )
    agent = AgentService(provider, registry, AgentRunRepository(session))

    run = agent.run(USER_ID, "Найди Дюну")

    assert run.status is AgentRunStatus.FAILED
    assert run.stop_reason == "repeated_tool_call"
    assert run.error == "Repeated tool call"
    assert len(run.steps) == 2
    assert run.steps[1].tool_results == []
    assert run.steps[1].error == "Repeated tool call"
    handler.assert_called_once()


def test_agent_returns_tool_error_and_allows_model_to_correct_it(
    session: Session,
) -> None:
    handler = Mock(return_value=SearchBooksResult(books=[]))
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, handler)
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="invalid-1",
                        name="search_books",
                        arguments={"query": "Дюна", "sql": "DROP TABLE books"},
                    )
                ],
            ),
            ModelResponse(
                text="Исправляю аргументы",
                tool_calls=[
                    ToolCall(
                        id="valid-1",
                        name="search_books",
                        arguments={"query": "Дюна"},
                    )
                ],
            ),
            ModelResponse(text="Поиск завершён."),
        ]
    )
    agent = AgentService(provider, registry, AgentRunRepository(session))

    run = agent.run(USER_ID, "Найди Дюну")

    assert run.status is AgentRunStatus.COMPLETED
    assert run.steps[0].tool_results[0]["error"]["code"] == "invalid_arguments"
    first_result = json.loads(provider.calls[1][-1].content)
    assert first_result["error"]["code"] == "invalid_arguments"
    handler.assert_called_once()


def test_agent_returns_unknown_tool_error_to_model(session: Session) -> None:
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="unknown-1",
                        name="execute_sql",
                        arguments={"query": "DROP TABLE books"},
                    )
                ],
            ),
            ModelResponse(text="Этот инструмент недоступен."),
        ]
    )
    agent = AgentService(provider, ToolRegistry(), AgentRunRepository(session))

    run = agent.run(USER_ID, "Удали таблицу книг")

    assert run.status is AgentRunStatus.COMPLETED
    assert run.steps[0].tool_results[0]["error"]["code"] == "unknown_tool"
    assert json.loads(provider.calls[1][-1].content)["tool_call_id"] == "unknown-1"


def test_agent_persists_provider_error_and_reraises(session: Session) -> None:
    provider = Mock()
    provider.generate.side_effect = LLMTimeoutError("internal SDK details")
    repository = AgentRunRepository(session)
    agent = AgentService(provider, ToolRegistry(), repository)

    with pytest.raises(LLMTimeoutError, match="internal SDK details"):
        agent.run(USER_ID, "Найди Дюну")

    run_id = session.scalar(select(AgentRun.id))
    assert run_id is not None
    run = repository.get_run(run_id)
    assert run is not None
    assert run.status is AgentRunStatus.FAILED
    assert run.stop_reason == "provider_error"
    assert run.error == "LLMTimeoutError"
    assert run.steps[0].response is None
    assert run.steps[0].error == "LLMTimeoutError"
    assert "internal SDK details" not in run.steps[0].error


def test_agent_persists_unexpected_tool_error_and_reraises(
    session: Session,
) -> None:
    handler = Mock(side_effect=RuntimeError("database is broken"))
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, handler)
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="search-1",
                        name="search_books",
                        arguments={"query": "Дюна"},
                    )
                ],
            )
        ]
    )
    repository = AgentRunRepository(session)
    agent = AgentService(provider, registry, repository)

    with pytest.raises(RuntimeError, match="database is broken"):
        agent.run(USER_ID, "Найди Дюну")

    run_id = session.scalar(select(AgentRun.id))
    assert run_id is not None
    run = repository.get_run(run_id)
    assert run is not None
    assert run.status is AgentRunStatus.FAILED
    assert run.stop_reason == "unexpected_error"
    assert run.error == "RuntimeError"
    assert run.steps[0].response["tool_calls"][0]["id"] == "search-1"
    assert run.steps[0].error == "RuntimeError"


def test_agent_rejects_non_positive_step_limit(session: Session) -> None:
    with pytest.raises(ValueError, match="max_steps must be at least 1"):
        AgentService(
            FakeLLMProvider([]),
            ToolRegistry(),
            AgentRunRepository(session),
            max_steps=0,
        )
