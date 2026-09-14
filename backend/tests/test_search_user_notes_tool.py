from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.memory.repository import MemoryRepository
from app.memory.service import MemoryService
from app.tools.memory import (
    SEARCH_USER_NOTES_TOOL,
    SearchUserNotesArguments,
    SearchUserNotesHandler,
    SearchUserNotesResult,
)
from app.tools.models import ToolAccess, ToolCall, ToolErrorCode
from app.tools.registry import ToolRegistry

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000002")


def test_search_user_notes_contract_is_strict_and_read_only() -> None:
    assert SEARCH_USER_NOTES_TOOL.access is ToolAccess.READ
    assert "current user's personal book notes" in SEARCH_USER_NOTES_TOOL.description
    assert SearchUserNotesArguments(query="экология").limit == 5

    with pytest.raises(ValidationError):
        SearchUserNotesArguments.model_validate(
            {"query": "экология", "user_id": str(OTHER_USER_ID)}
        )
    with pytest.raises(ValidationError):
        SearchUserNotesArguments(query="экология", limit=11)

    schema = SEARCH_USER_NOTES_TOOL.arguments_model.model_json_schema()
    assert schema["additionalProperties"] is False
    assert "user_id" not in schema["properties"]


def test_handler_returns_only_configured_users_citations(
    session: Session,
) -> None:
    service = MemoryService(MemoryRepository(session))
    own = service.create_note(USER_ID, "Экология и политика воды")
    service.create_note(OTHER_USER_ID, "Экология чужого мира")
    registry = ToolRegistry()
    registry.register(
        SEARCH_USER_NOTES_TOOL,
        SearchUserNotesHandler(service, USER_ID),
    )

    result = registry.execute(
        ToolCall(
            id="notes-1",
            name="search_user_notes",
            arguments={"query": "экология", "limit": 5},
        )
    )

    assert result.error is None
    output = SearchUserNotesResult.model_validate(result.output)
    assert [citation.note_id for citation in output.citations] == [own.id]
    assert output.citations[0].chunk_id == own.chunks[0].id


def test_invalid_arguments_do_not_reach_handler(session: Session) -> None:
    service = MemoryService(MemoryRepository(session))
    registry = ToolRegistry()
    registry.register(
        SEARCH_USER_NOTES_TOOL,
        SearchUserNotesHandler(service, USER_ID),
    )

    result = registry.execute(
        ToolCall(
            id="notes-invalid",
            name="search_user_notes",
            arguments={"query": "", "limit": 0},
        )
    )

    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGUMENTS
