from uuid import UUID

from sqlalchemy.orm import Session

from app.config import Settings
from app.dependencies import (
    get_agent_repository,
    get_agent_service,
    get_tool_registry,
)
from app.llm.fake import FakeLLMProvider
from app.llm.models import ModelResponse
from app.memory.repository import MemoryRepository
from app.memory.service import MemoryService
from app.models import AgentRunStatus
from app.repository import BookRepository
from app.service import BookService
from app.tools.models import ToolCall, ToolErrorCode

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000002")
DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")


def test_tool_registry_wires_seven_allowed_tools_for_configured_user(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    memory_service = MemoryService(MemoryRepository(session))
    registry = get_tool_registry(
        service,
        memory_service,
        Settings(demo_user_id=USER_ID),
    )

    assert [definition.name for definition in registry.definitions()] == [
        "search_books",
        "find_similar_books",
        "get_user_library",
        "add_book",
        "update_book_status",
        "search_user_notes",
        "remove_book",
    ]

    result = registry.execute(
        ToolCall(
            id="add-1",
            name="add_book",
            arguments={
                "book_id": str(DUNE_ID),
                "status": "want_to_read",
            },
        )
    )

    assert result.error is None
    assert len(service.get_library(USER_ID)) == 1
    assert service.get_library(OTHER_USER_ID) == []


def test_wired_registry_keeps_unknown_tool_controlled(session: Session) -> None:
    service = BookService(BookRepository(session))
    registry = get_tool_registry(
        service,
        MemoryService(MemoryRepository(session)),
        Settings(demo_user_id=USER_ID),
    )

    result = registry.execute(
        ToolCall(
            id="unknown-1",
            name="execute_sql",
            arguments={"query": "DROP TABLE books"},
        )
    )

    assert result.error is not None
    assert result.error.code is ToolErrorCode.UNKNOWN_TOOL


def test_agent_service_uses_configured_limits(session: Session) -> None:
    settings = Settings(
        demo_user_id=USER_ID,
        agent_max_steps=1,
        agent_history_max_tool_rounds=2,
    )
    book_service = BookService(BookRepository(session))
    registry = get_tool_registry(
        book_service,
        MemoryService(MemoryRepository(session)),
        settings,
    )
    repository = get_agent_repository(session)
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
    agent = get_agent_service(provider, registry, repository, settings)

    run = agent.run(USER_ID, "Найди Дюну")

    assert run.status is AgentRunStatus.STEP_LIMIT_EXCEEDED
    assert run.stop_reason == "max_steps"
    assert len(run.steps) == 1
    assert agent._history_max_tool_rounds == 2
