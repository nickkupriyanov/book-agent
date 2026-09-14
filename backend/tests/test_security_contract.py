from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.agent.repository import AgentRunRepository
from app.agent.service import AgentService
from app.catalog.local import LocalBookCatalog
from app.config import Settings
from app.dependencies import get_tool_registry
from app.llm.fake import FakeLLMProvider
from app.llm.models import ModelResponse
from app.memory.exceptions import NoteNotFoundError
from app.memory.repository import MemoryRepository
from app.memory.service import MemoryService
from app.models import AgentRunStatus, ReadingStatus
from app.repository import BookRepository
from app.service import BookService
from app.tools.models import ToolCall, ToolErrorCode

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000002")
DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")
EXPECTED_TOOLS = {
    "search_books",
    "find_similar_books",
    "get_user_library",
    "add_book",
    "update_book_status",
    "search_user_notes",
    "remove_book",
}


def build_services(session: Session) -> tuple[BookService, MemoryService]:
    repository = BookRepository(session)
    return (
        BookService(repository, LocalBookCatalog(repository)),
        MemoryService(MemoryRepository(session)),
    )


def build_registry(session: Session):
    book_service, memory_service = build_services(session)
    return get_tool_registry(
        service=book_service,
        memory_service=memory_service,
        settings=Settings(demo_user_id=USER_ID),
    )


def test_tool_allowlist_has_strict_server_scoped_arguments(session: Session) -> None:
    registry = build_registry(session)
    definitions = registry.definitions()

    assert {definition.name for definition in definitions} == EXPECTED_TOOLS
    for definition in definitions:
        schema = definition.arguments_model.model_json_schema()
        assert schema["additionalProperties"] is False
        assert "user_id" not in schema.get("properties", {})


def test_unknown_and_injected_tool_calls_have_no_side_effect(session: Session) -> None:
    book_service, _ = build_services(session)
    registry = build_registry(session)

    unknown = registry.execute(
        ToolCall(
            id="attack-1",
            name="execute_sql",
            arguments={"query": "DELETE FROM library_entries"},
        )
    )
    injected = registry.execute(
        ToolCall(
            id="attack-2",
            name="add_book",
            arguments={
                "book_id": str(DUNE_ID),
                "status": "reading",
                "user_id": str(OTHER_USER_ID),
            },
        )
    )

    assert unknown.error is not None
    assert unknown.error.code is ToolErrorCode.UNKNOWN_TOOL
    assert injected.error is not None
    assert injected.error.code is ToolErrorCode.INVALID_ARGUMENTS
    assert book_service.get_library(USER_ID) == []
    assert book_service.get_library(OTHER_USER_ID) == []


def test_destructive_call_pauses_before_database_change(session: Session) -> None:
    book_service, _ = build_services(session)
    book_service.add_book(USER_ID, DUNE_ID, ReadingStatus.READING)
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="remove-security-1",
                        name="remove_book",
                        arguments={"book_id": str(DUNE_ID)},
                    )
                ],
            )
        ]
    )
    service = AgentService(
        provider,
        build_registry(session),
        AgentRunRepository(session),
    )

    run = service.run(USER_ID, "Удали Дюну")

    assert run.status is AgentRunStatus.WAITING_FOR_APPROVAL
    assert run.pending_action is not None
    assert run.steps[0].tool_results == []
    assert [entry.book_id for entry in book_service.get_library(USER_ID)] == [DUNE_ID]


def test_library_and_memory_are_filtered_by_server_user(session: Session) -> None:
    book_service, memory_service = build_services(session)
    book_service.add_book(OTHER_USER_ID, DUNE_ID, ReadingStatus.FINISHED)
    other_note = memory_service.create_note(
        OTHER_USER_ID,
        "Секретная заметка про Арракис",
        DUNE_ID,
    )

    assert book_service.get_library(USER_ID) == []
    with pytest.raises(NoteNotFoundError):
        memory_service.get_note(USER_ID, other_note.id)
    assert memory_service.search_notes(USER_ID, "Арракис") == []
