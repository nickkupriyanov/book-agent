from unittest.mock import create_autospec
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import Book, LibraryEntry, ReadingStatus
from app.repository import BookRepository
from app.service import BookService
from app.tools.library import (
    ADD_BOOK_TOOL,
    AddBookArguments,
    AddBookHandler,
    AddBookResult,
)
from app.tools.models import ToolAccess, ToolCall, ToolErrorCode
from app.tools.registry import ToolRegistry

DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")


def test_add_book_definition_is_strict_write_tool_without_user_id() -> None:
    schema = ADD_BOOK_TOOL.arguments_model.model_json_schema()

    assert ADD_BOOK_TOOL.name == "add_book"
    assert ADD_BOOK_TOOL.access is ToolAccess.WRITE
    assert ADD_BOOK_TOOL.arguments_model is AddBookArguments
    assert ADD_BOOK_TOOL.result_model is AddBookResult
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"book_id", "status"}
    assert "user_id" not in schema["properties"]


def test_add_book_arguments_validate_uuid_status_and_extra_fields() -> None:
    arguments = AddBookArguments.model_validate(
        {"book_id": str(DUNE_ID), "status": "want_to_read"}
    )

    assert arguments.book_id == DUNE_ID
    assert arguments.status is ReadingStatus.WANT_TO_READ

    invalid_arguments = (
        {"book_id": "not-a-uuid", "status": "want_to_read"},
        {"book_id": str(DUNE_ID), "status": "unknown"},
        {
            "book_id": str(DUNE_ID),
            "status": "want_to_read",
            "user_id": str(DEMO_USER_ID),
        },
    )
    for invalid_argument in invalid_arguments:
        with pytest.raises(ValidationError):
            AddBookArguments.model_validate(invalid_argument)


def test_add_book_handler_uses_scoped_user_and_returns_entry() -> None:
    entry = LibraryEntry(
        user_id=DEMO_USER_ID,
        book_id=DUNE_ID,
        status=ReadingStatus.WANT_TO_READ,
    )
    entry.book = Book(
        id=DUNE_ID,
        title="Дюна",
        author="Фрэнк Герберт",
        tags=["politics", "science_fiction", "space_opera"],
    )
    service = create_autospec(BookService, instance=True)
    service.add_book.return_value = entry
    handler = AddBookHandler(service=service, user_id=DEMO_USER_ID)
    arguments = AddBookArguments(
        book_id=DUNE_ID,
        status=ReadingStatus.WANT_TO_READ,
    )

    result = handler(arguments)

    service.add_book.assert_called_once_with(
        user_id=DEMO_USER_ID,
        book_id=DUNE_ID,
        status=ReadingStatus.WANT_TO_READ,
    )
    assert result.entry.book.title == "Дюна"
    assert result.entry.status is ReadingStatus.WANT_TO_READ


def test_registry_executes_add_book_and_changes_database(session: Session) -> None:
    service = BookService(BookRepository(session))
    registry = ToolRegistry()
    registry.register(
        ADD_BOOK_TOOL,
        AddBookHandler(service=service, user_id=DEMO_USER_ID),
    )

    result = registry.execute(
        ToolCall(
            id="call-add-1",
            name="add_book",
            arguments={"book_id": str(DUNE_ID), "status": "want_to_read"},
        )
    )

    assert result.error is None
    assert len(service.get_library(DEMO_USER_ID)) == 1
    assert service.get_library(DEMO_USER_ID)[0].status is ReadingStatus.WANT_TO_READ


def test_registry_returns_book_not_found_without_changing_database(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    registry = ToolRegistry()
    registry.register(
        ADD_BOOK_TOOL,
        AddBookHandler(service=service, user_id=DEMO_USER_ID),
    )

    result = registry.execute(
        ToolCall(
            id="call-add-2",
            name="add_book",
            arguments={"book_id": str(uuid4()), "status": "want_to_read"},
        )
    )

    assert result.output is None
    assert result.error is not None
    assert result.error.code is ToolErrorCode.BOOK_NOT_FOUND
    assert service.get_library(DEMO_USER_ID) == []


def test_registry_returns_duplicate_error_without_second_entry(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    registry = ToolRegistry()
    registry.register(
        ADD_BOOK_TOOL,
        AddBookHandler(service=service, user_id=DEMO_USER_ID),
    )
    call = ToolCall(
        id="call-add-3",
        name="add_book",
        arguments={"book_id": str(DUNE_ID), "status": "want_to_read"},
    )

    first = registry.execute(call)
    second = registry.execute(call.model_copy(update={"id": "call-add-4"}))

    assert first.error is None
    assert second.output is None
    assert second.error is not None
    assert second.error.code is ToolErrorCode.BOOK_ALREADY_IN_LIBRARY
    assert len(service.get_library(DEMO_USER_ID)) == 1
