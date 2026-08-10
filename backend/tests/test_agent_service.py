import json
from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.repository import AgentRunRepository
from app.agent.service import AgentService, WORKING_STATE_PREFIX
from app.agent.state import AgentWorkingState, CompletedAction
from app.llm.fake import FakeLLMProvider
from app.llm.exceptions import LLMTimeoutError
from app.llm.models import Message, MessageRole, ModelResponse
from app.models import AgentRun, AgentRunStatus, ReadingStatus
from app.repository import BookRepository
from app.service import BookService
from app.tools.books import (
    SEARCH_BOOKS_TOOL,
    SearchBooksHandler,
    SearchBooksResult,
)
from app.tools.library import (
    ADD_BOOK_TOOL,
    REMOVE_BOOK_TOOL,
    AddBookHandler,
    RemoveBookApprovalSummary,
    RemoveBookHandler,
)
from app.tools.models import ToolCall, ToolErrorCode
from app.tools.registry import ToolRegistry

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")
NINETEEN_EIGHTY_FOUR_ID = UUID("10000000-0000-0000-0000-000000000002")


def working_state_from_provider_call(
    messages: list[Message],
) -> AgentWorkingState:
    system_message = messages[0]
    assert system_message.role is MessageRole.SYSTEM
    _, serialized_state = system_message.content.split(
        WORKING_STATE_PREFIX,
        maxsplit=1,
    )
    return AgentWorkingState.model_validate(json.loads(serialized_state))


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
    assert AgentWorkingState.model_validate(run.working_state) == (
        AgentWorkingState(
            goal="Найди Дюну и добавь в список на чтение",
            completed_actions=[
                CompletedAction(
                    step_number=1,
                    tool_call_id="search-1",
                    tool_name="search_books",
                ),
                CompletedAction(
                    step_number=2,
                    tool_call_id="add-1",
                    tool_name="add_book",
                ),
            ],
            initial_step_budget=5,
            remaining_step_budget=2,
        )
    )

    library = book_service.get_library(USER_ID)
    assert len(library) == 1
    assert library[0].book.id == DUNE_ID
    assert library[0].status is ReadingStatus.WANT_TO_READ

    assert len(provider.calls) == 3
    assert provider.calls[1][-1].role is MessageRole.TOOL
    assert provider.calls[1][-1].tool_call_id == "search-1"
    assert json.loads(provider.calls[1][-1].content)["tool_call_id"] == "search-1"
    assert provider.calls[2][-1].tool_call_id == "add-1"
    provider_states = [
        working_state_from_provider_call(call) for call in provider.calls
    ]
    assert [state.remaining_step_budget for state in provider_states] == [
        5,
        4,
        3,
    ]
    assert [
        [action.tool_name for action in state.completed_actions]
        for state in provider_states
    ] == [[], ["search_books"], ["search_books", "add_book"]]
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
    state = AgentWorkingState.model_validate(run.working_state)
    assert state.initial_step_budget == 2
    assert state.remaining_step_budget == 0


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
    state = AgentWorkingState.model_validate(run.working_state)
    assert state.remaining_step_budget == 3
    assert [action.tool_call_id for action in state.completed_actions] == [
        "search-1"
    ]
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
    state = AgentWorkingState.model_validate(run.working_state)
    assert [action.tool_call_id for action in state.completed_actions] == [
        "valid-1"
    ]


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
    state = AgentWorkingState.model_validate(run.working_state)
    assert state.remaining_step_budget == 4
    assert state.completed_actions == ()
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
    state = AgentWorkingState.model_validate(run.working_state)
    assert state.remaining_step_budget == 4
    assert state.completed_actions == ()
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


def test_agent_pauses_before_destructive_handler_and_persists_action(
    session: Session,
) -> None:
    book_service = BookService(BookRepository(session))
    book_service.add_book(USER_ID, DUNE_ID, ReadingStatus.READING)
    remove_handler = Mock(wraps=RemoveBookHandler(book_service, USER_ID))
    registry = ToolRegistry()
    registry.register(
        REMOVE_BOOK_TOOL,
        remove_handler,
        approval_summary=RemoveBookApprovalSummary(book_service, USER_ID),
    )
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="remove-1",
                        name="remove_book",
                        arguments={"book_id": str(DUNE_ID)},
                    )
                ],
            )
        ]
    )
    agent = AgentService(provider, registry, AgentRunRepository(session))

    run = agent.run(USER_ID, "Удали Дюну из моей библиотеки")

    assert run.status is AgentRunStatus.WAITING_FOR_APPROVAL
    assert run.version == 1
    assert run.final_answer is None
    assert run.stop_reason is None
    assert run.error is None
    assert len(run.steps) == 1
    assert run.steps[0].response["tool_calls"][0]["id"] == "remove-1"
    assert run.steps[0].tool_results == []
    assert run.pending_action is not None
    assert run.pending_action.tool_call_id == "remove-1"
    assert run.pending_action.arguments == {"book_id": str(DUNE_ID)}
    assert run.pending_action.summary == (
        "Удалить «Дюна» (Фрэнк Герберт) из вашей библиотеки."
    )
    assert run.pending_action.expected_run_version == 1
    assert len(book_service.get_library(USER_ID)) == 1
    assert len(provider.calls) == 1
    remove_handler.assert_not_called()
    state = AgentWorkingState.model_validate(run.working_state)
    assert state.remaining_step_budget == 4
    assert state.completed_actions == ()


@pytest.mark.parametrize(
    "tool_calls",
    [
        [
            ToolCall(
                id="add-1",
                name="add_book",
                arguments={
                    "book_id": str(NINETEEN_EIGHTY_FOUR_ID),
                    "status": "want_to_read",
                },
            ),
            ToolCall(
                id="remove-1",
                name="remove_book",
                arguments={"book_id": str(DUNE_ID)},
            ),
        ],
        [
            ToolCall(
                id="remove-1",
                name="remove_book",
                arguments={"book_id": str(DUNE_ID)},
            ),
            ToolCall(
                id="remove-2",
                name="remove_book",
                arguments={"book_id": str(DUNE_ID)},
            ),
        ],
    ],
    ids=["mixed", "multiple-approval"],
)
def test_agent_rejects_ambiguous_approval_batch_before_all_handlers(
    session: Session,
    tool_calls: list[ToolCall],
) -> None:
    book_service = BookService(BookRepository(session))
    book_service.add_book(USER_ID, DUNE_ID, ReadingStatus.READING)
    add_handler = Mock(wraps=AddBookHandler(book_service, USER_ID))
    remove_handler = Mock(wraps=RemoveBookHandler(book_service, USER_ID))
    registry = ToolRegistry()
    registry.register(ADD_BOOK_TOOL, add_handler)
    registry.register(
        REMOVE_BOOK_TOOL,
        remove_handler,
        approval_summary=RemoveBookApprovalSummary(book_service, USER_ID),
    )
    provider = FakeLLMProvider(
        [
            ModelResponse(text="", tool_calls=tool_calls),
            ModelResponse(text="Отправлю опасное действие отдельно."),
        ]
    )
    agent = AgentService(provider, registry, AgentRunRepository(session))

    run = agent.run(USER_ID, "Измени мою библиотеку")

    assert run.status is AgentRunStatus.COMPLETED
    assert run.pending_action is None
    assert len(run.steps[0].tool_results) == len(tool_calls)
    assert {
        result["error"]["code"] for result in run.steps[0].tool_results
    } == {ToolErrorCode.AMBIGUOUS_APPROVAL_BATCH.value}
    assert [entry.book_id for entry in book_service.get_library(USER_ID)] == [
        DUNE_ID
    ]
    add_handler.assert_not_called()
    remove_handler.assert_not_called()


def test_agent_rejects_non_positive_approval_ttl(session: Session) -> None:
    with pytest.raises(
        ValueError,
        match="approval_ttl_seconds must be at least 1",
    ):
        AgentService(
            FakeLLMProvider([]),
            ToolRegistry(),
            AgentRunRepository(session),
            approval_ttl_seconds=0,
        )
