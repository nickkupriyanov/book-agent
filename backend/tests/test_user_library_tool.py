from unittest.mock import create_autospec
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import ReadingStatus
from app.repository import BookRepository
from app.service import BookService
from app.tools.books import SEARCH_BOOKS_TOOL, SearchBooksHandler
from app.tools.library import (
    GET_USER_LIBRARY_TOOL,
    GetUserLibraryArguments,
    GetUserLibraryHandler,
    GetUserLibraryResult,
)
from app.tools.models import ToolAccess, ToolCall
from app.tools.registry import ToolRegistry

DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")


def test_get_user_library_definition_is_strict_read_tool_without_user_id() -> None:
    schema = GET_USER_LIBRARY_TOOL.arguments_model.model_json_schema()

    assert GET_USER_LIBRARY_TOOL.name == "get_user_library"
    assert GET_USER_LIBRARY_TOOL.access is ToolAccess.READ
    assert GET_USER_LIBRARY_TOOL.arguments_model is GetUserLibraryArguments
    assert GET_USER_LIBRARY_TOOL.result_model is GetUserLibraryResult
    assert schema["additionalProperties"] is False
    assert "user_id" not in schema["properties"]


def test_get_user_library_arguments_validate_optional_status() -> None:
    arguments = GetUserLibraryArguments.model_validate({"status": "reading"})

    assert arguments.status is ReadingStatus.READING
    assert GetUserLibraryArguments().status is None

    with pytest.raises(ValidationError):
        GetUserLibraryArguments.model_validate({"status": "unknown"})
    with pytest.raises(ValidationError):
        GetUserLibraryArguments.model_validate({"user_id": str(DEMO_USER_ID)})


def test_get_user_library_handler_uses_scoped_user_and_status() -> None:
    service = create_autospec(BookService, instance=True)
    service.get_library.return_value = []
    handler = GetUserLibraryHandler(service=service, user_id=DEMO_USER_ID)

    result = handler(GetUserLibraryArguments(status=ReadingStatus.READING))

    service.get_library.assert_called_once_with(
        user_id=DEMO_USER_ID,
        status=ReadingStatus.READING,
    )
    assert result == GetUserLibraryResult(entries=[])


def test_get_user_library_handler_converts_database_entry(session: Session) -> None:
    service = BookService(BookRepository(session))
    service.add_book(DEMO_USER_ID, DUNE_ID, ReadingStatus.FINISHED)
    handler = GetUserLibraryHandler(service=service, user_id=DEMO_USER_ID)

    result = handler(GetUserLibraryArguments())

    assert len(result.entries) == 1
    assert result.entries[0].book.id == DUNE_ID
    assert result.entries[0].book.title == "Дюна"
    assert result.entries[0].status is ReadingStatus.FINISHED


def test_registry_executes_library_tool_alongside_search_tool(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    service.add_book(DEMO_USER_ID, DUNE_ID, ReadingStatus.FINISHED)
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, SearchBooksHandler(service))
    registry.register(
        GET_USER_LIBRARY_TOOL,
        GetUserLibraryHandler(service=service, user_id=DEMO_USER_ID),
    )

    result = registry.execute(
        ToolCall(
            id="call-library-1",
            name="get_user_library",
            arguments={"status": "finished"},
        )
    )

    assert [definition.name for definition in registry.definitions()] == [
        "search_books",
        "get_user_library",
    ]
    assert result.error is None
    assert result.output is not None
    output = GetUserLibraryResult.model_validate(result.output)
    assert output.entries[0].book.title == "Дюна"
    assert output.entries[0].status is ReadingStatus.FINISHED
