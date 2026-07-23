import json
from uuid import UUID

from sqlalchemy.orm import Session

from app.agent.repository import AgentRunRepository
from app.agent.service import AgentService
from app.llm.fake import FakeLLMProvider
from app.llm.models import MessageRole, ModelResponse
from app.models import AgentRunStatus, ReadingStatus
from app.repository import BookRepository
from app.service import BookService
from app.tools.books import SEARCH_BOOKS_TOOL, SearchBooksHandler
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
