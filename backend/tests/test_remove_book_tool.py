from unittest.mock import create_autospec
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import Book, LibraryEntry, ReadingStatus
from app.repository import BookRepository
from app.service import BookService
from app.tools.library import (
    REMOVE_BOOK_TOOL,
    RemoveBookArguments,
    RemoveBookHandler,
    RemoveBookResult,
)
from app.tools.models import ToolAccess, ToolCall, ToolErrorCode
from app.tools.registry import ToolRegistry

DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")


def test_remove_book_definition_is_strict_destructive_tool() -> None:
    schema = REMOVE_BOOK_TOOL.arguments_model.model_json_schema()

    assert REMOVE_BOOK_TOOL.name == "remove_book"
    assert REMOVE_BOOK_TOOL.access is ToolAccess.DESTRUCTIVE
    assert REMOVE_BOOK_TOOL.arguments_model is RemoveBookArguments
    assert REMOVE_BOOK_TOOL.result_model is RemoveBookResult
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["book_id"]
    assert "user_id" not in schema["properties"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"book_id": "not-a-uuid"},
        {"book_id": str(DUNE_ID), "user_id": str(DEMO_USER_ID)},
    ],
)
def test_remove_book_arguments_reject_invalid_input(
    arguments: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        RemoveBookArguments.model_validate(arguments)


def test_remove_book_handler_uses_scoped_user_and_returns_minimal_snapshot() -> None:
    entry = LibraryEntry(
        user_id=DEMO_USER_ID,
        book_id=DUNE_ID,
        status=ReadingStatus.READING,
    )
    entry.book = Book(
        id=DUNE_ID,
        title="Дюна",
        author="Фрэнк Герберт",
        tags=["politics", "science_fiction", "space_opera"],
    )
    service = create_autospec(BookService, instance=True)
    service.remove_book.return_value = entry
    handler = RemoveBookHandler(service=service, user_id=DEMO_USER_ID)

    result = handler(RemoveBookArguments(book_id=DUNE_ID))

    service.remove_book.assert_called_once_with(
        user_id=DEMO_USER_ID,
        book_id=DUNE_ID,
    )
    assert result == RemoveBookResult(
        book_id=DUNE_ID,
        title="Дюна",
        author="Фрэнк Герберт",
        status=ReadingStatus.READING,
    )
    assert "user_id" not in result.model_dump()
    assert "tags" not in result.model_dump()


@pytest.mark.parametrize(
    "arguments",
    [
        {"book_id": "not-a-uuid"},
        {"book_id": str(DUNE_ID), "user_id": str(DEMO_USER_ID)},
    ],
)
def test_registry_rejects_invalid_remove_arguments_before_service(
    arguments: dict[str, str],
) -> None:
    service = create_autospec(BookService, instance=True)
    registry = ToolRegistry()
    registry.register(
        REMOVE_BOOK_TOOL,
        RemoveBookHandler(service=service, user_id=DEMO_USER_ID),
    )

    result = registry.execute(
        ToolCall(id="call-remove-invalid", name="remove_book", arguments=arguments)
    )

    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGUMENTS
    service.remove_book.assert_not_called()


def test_registry_removes_library_entry_but_keeps_catalog_book(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    service.add_book(DEMO_USER_ID, DUNE_ID, ReadingStatus.READING)
    registry = ToolRegistry()
    registry.register(
        REMOVE_BOOK_TOOL,
        RemoveBookHandler(service=service, user_id=DEMO_USER_ID),
    )

    result = registry.execute(
        ToolCall(
            id="call-remove-1",
            name="remove_book",
            arguments={"book_id": str(DUNE_ID)},
        )
    )

    assert result.error is None
    assert result.output == {
        "book_id": str(DUNE_ID),
        "title": "Дюна",
        "author": "Фрэнк Герберт",
        "status": "reading",
    }
    assert service.get_library(DEMO_USER_ID) == []
    assert service.get_book(DUNE_ID).title == "Дюна"


def test_registry_reports_repeated_direct_removal_as_missing(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    service.add_book(DEMO_USER_ID, DUNE_ID, ReadingStatus.READING)
    registry = ToolRegistry()
    registry.register(
        REMOVE_BOOK_TOOL,
        RemoveBookHandler(service=service, user_id=DEMO_USER_ID),
    )
    call = ToolCall(
        id="call-remove-2",
        name="remove_book",
        arguments={"book_id": str(DUNE_ID)},
    )

    first = registry.execute(call)
    repeated = registry.execute(call.model_copy(update={"id": "call-remove-3"}))

    assert first.error is None
    assert repeated.output is None
    assert repeated.error is not None
    assert repeated.error.code is ToolErrorCode.LIBRARY_ENTRY_NOT_FOUND
