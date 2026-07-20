from unittest.mock import create_autospec
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import Book, LibraryEntry, ReadingStatus
from app.repository import BookRepository
from app.service import BookService
from app.tools.library import (
    UPDATE_BOOK_STATUS_TOOL,
    UpdateBookStatusArguments,
    UpdateBookStatusHandler,
    UpdateBookStatusResult,
)
from app.tools.models import ToolAccess, ToolCall, ToolErrorCode
from app.tools.registry import ToolRegistry

DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")


def test_update_book_status_definition_is_strict_write_tool() -> None:
    schema = UPDATE_BOOK_STATUS_TOOL.arguments_model.model_json_schema()

    assert UPDATE_BOOK_STATUS_TOOL.name == "update_book_status"
    assert UPDATE_BOOK_STATUS_TOOL.access is ToolAccess.WRITE
    assert UPDATE_BOOK_STATUS_TOOL.arguments_model is UpdateBookStatusArguments
    assert UPDATE_BOOK_STATUS_TOOL.result_model is UpdateBookStatusResult
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"book_id", "status"}
    assert "user_id" not in schema["properties"]


def test_update_book_status_arguments_reject_invalid_input() -> None:
    invalid_arguments = (
        {"book_id": "not-a-uuid", "status": "finished"},
        {"book_id": str(DUNE_ID), "status": "unknown"},
        {
            "book_id": str(DUNE_ID),
            "status": "finished",
            "user_id": str(DEMO_USER_ID),
        },
    )

    for invalid_argument in invalid_arguments:
        with pytest.raises(ValidationError):
            UpdateBookStatusArguments.model_validate(invalid_argument)


def test_update_book_status_handler_uses_scoped_user_and_returns_entry() -> None:
    entry = LibraryEntry(
        user_id=DEMO_USER_ID,
        book_id=DUNE_ID,
        status=ReadingStatus.FINISHED,
    )
    entry.book = Book(id=DUNE_ID, title="Дюна", author="Фрэнк Герберт")
    service = create_autospec(BookService, instance=True)
    service.update_status.return_value = entry
    handler = UpdateBookStatusHandler(service=service, user_id=DEMO_USER_ID)
    arguments = UpdateBookStatusArguments(
        book_id=DUNE_ID,
        status=ReadingStatus.FINISHED,
    )

    result = handler(arguments)

    service.update_status.assert_called_once_with(
        user_id=DEMO_USER_ID,
        book_id=DUNE_ID,
        status=ReadingStatus.FINISHED,
    )
    assert result.entry.book.title == "Дюна"
    assert result.entry.status is ReadingStatus.FINISHED


def test_registry_updates_existing_library_entry(session: Session) -> None:
    service = BookService(BookRepository(session))
    service.add_book(DEMO_USER_ID, DUNE_ID, ReadingStatus.READING)
    registry = ToolRegistry()
    registry.register(
        UPDATE_BOOK_STATUS_TOOL,
        UpdateBookStatusHandler(service=service, user_id=DEMO_USER_ID),
    )

    result = registry.execute(
        ToolCall(
            id="call-update-1",
            name="update_book_status",
            arguments={"book_id": str(DUNE_ID), "status": "finished"},
        )
    )

    entries = service.get_library(DEMO_USER_ID)
    assert result.error is None
    assert result.output is not None
    assert result.output["entry"]["status"] == "finished"
    assert len(entries) == 1
    assert entries[0].status is ReadingStatus.FINISHED


def test_registry_returns_missing_entry_error_without_creating_one(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    registry = ToolRegistry()
    registry.register(
        UPDATE_BOOK_STATUS_TOOL,
        UpdateBookStatusHandler(service=service, user_id=DEMO_USER_ID),
    )

    result = registry.execute(
        ToolCall(
            id="call-update-2",
            name="update_book_status",
            arguments={"book_id": str(DUNE_ID), "status": "finished"},
        )
    )

    assert result.output is None
    assert result.error is not None
    assert result.error.code is ToolErrorCode.LIBRARY_ENTRY_NOT_FOUND
    assert service.get_library(DEMO_USER_ID) == []
