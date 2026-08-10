from dataclasses import replace
from unittest.mock import Mock
from uuid import UUID

import pytest

from app.tools.books import (
    SEARCH_BOOKS_TOOL,
    BookToolResult,
    SearchBooksArguments,
    SearchBooksResult,
)
from app.tools.exceptions import ToolExecutionError
from app.tools.models import (
    ToolCall,
    ToolAccess,
    ToolError,
    ToolErrorCode,
    ToolResult,
)
from app.tools.registry import DuplicateToolError, PreparedToolCall, ToolRegistry

DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")


def test_registry_exposes_registered_definitions() -> None:
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, Mock())

    assert registry.definitions() == (SEARCH_BOOKS_TOOL,)


def test_registry_validates_arguments_and_calls_handler() -> None:
    handler = Mock(
        return_value=SearchBooksResult(
            books=[
                BookToolResult(
                    id=DUNE_ID,
                    title="Дюна",
                    author="Фрэнк Герберт",
                    tags=["politics", "science_fiction", "space_opera"],
                )
            ]
        )
    )
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, handler)

    result = registry.execute(
        ToolCall(
            id="call-1",
            name="search_books",
            arguments={"query": "Дюна", "limit": 5},
        )
    )

    handler.assert_called_once_with(SearchBooksArguments(query="Дюна", limit=5))
    assert result.tool_call_id == "call-1"
    assert result.tool_name == "search_books"
    assert result.output == {
        "books": [
            {
                "id": str(DUNE_ID),
                "title": "Дюна",
                "author": "Фрэнк Герберт",
                "tags": ["politics", "science_fiction", "space_opera"],
            }
        ]
    }
    assert result.error is None


def test_registry_prepares_valid_call_without_calling_handler() -> None:
    handler = Mock(return_value=SearchBooksResult(books=[]))
    registry = ToolRegistry()
    destructive_tool = replace(
        SEARCH_BOOKS_TOOL,
        name="remove_book",
        access=ToolAccess.DESTRUCTIVE,
    )
    registry.register(destructive_tool, handler)

    prepared = registry.prepare(
        ToolCall(
            id="call-prepare-1",
            name="remove_book",
            arguments={"query": "Дюна"},
        )
    )

    assert isinstance(prepared, PreparedToolCall)
    assert prepared.definition is destructive_tool
    assert prepared.arguments == SearchBooksArguments(query="Дюна", limit=20)
    assert prepared.canonical_arguments == {"query": "Дюна", "limit": 20}
    handler.assert_not_called()

    result = registry.execute_prepared(prepared)

    handler.assert_called_once_with(SearchBooksArguments(query="Дюна", limit=20))
    assert result.output == {"books": []}


def test_registry_rejects_invalid_arguments_during_preparation() -> None:
    handler = Mock(return_value=SearchBooksResult(books=[]))
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, handler)

    result = registry.prepare(
        ToolCall(
            id="call-prepare-2",
            name="search_books",
            arguments={"query": "Дюна", "sql": "DROP TABLE books"},
        )
    )

    handler.assert_not_called()
    assert result == ToolResult(
        tool_call_id="call-prepare-2",
        tool_name="search_books",
        error=ToolError(
            code=ToolErrorCode.INVALID_ARGUMENTS,
            message="Tool arguments are invalid",
        ),
    )


def test_registry_rejects_invalid_arguments_before_handler() -> None:
    handler = Mock(return_value=SearchBooksResult(books=[]))
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, handler)

    result = registry.execute(
        ToolCall(
            id="call-2",
            name="search_books",
            arguments={"query": "Дюна", "sql": "DROP TABLE books"},
        )
    )

    handler.assert_not_called()
    assert result.output is None
    assert result.error == ToolError(
        code=ToolErrorCode.INVALID_ARGUMENTS,
        message="Tool arguments are invalid",
    )


def test_registry_rejects_unknown_tool() -> None:
    registry = ToolRegistry()

    result = registry.execute(
        ToolCall(
            id="call-3",
            name="execute_sql",
            arguments={"query": "DROP TABLE books"},
        )
    )

    assert result.output is None
    assert result.error == ToolError(
        code=ToolErrorCode.UNKNOWN_TOOL,
        message="Tool is not available",
    )


def test_registry_rejects_duplicate_name() -> None:
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, Mock())

    with pytest.raises(DuplicateToolError, match="Tool already registered: search_books"):
        registry.register(SEARCH_BOOKS_TOOL, Mock())


def test_registry_validates_handler_result() -> None:
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, Mock(return_value={"unexpected": True}))

    result = registry.execute(
        ToolCall(
            id="call-4",
            name="search_books",
            arguments={"query": "Дюна"},
        )
    )

    assert result.output is None
    assert result.error == ToolError(
        code=ToolErrorCode.INVALID_RESULT,
        message="Tool returned an invalid result",
    )


def test_registry_does_not_hide_unexpected_handler_error() -> None:
    registry = ToolRegistry()
    registry.register(
        SEARCH_BOOKS_TOOL,
        Mock(side_effect=RuntimeError("unexpected bug")),
    )

    with pytest.raises(RuntimeError, match="unexpected bug"):
        registry.execute(
            ToolCall(
                id="call-5",
                name="search_books",
                arguments={"query": "Дюна"},
            )
        )


def test_registry_converts_controlled_execution_error() -> None:
    registry = ToolRegistry()
    registry.register(
        SEARCH_BOOKS_TOOL,
        Mock(
            side_effect=ToolExecutionError(
                code=ToolErrorCode.BOOK_NOT_FOUND,
                message="Book was not found",
            )
        ),
    )

    result = registry.execute(
        ToolCall(
            id="call-6",
            name="search_books",
            arguments={"query": "Дюна"},
        )
    )

    assert result.output is None
    assert result.error == ToolError(
        code=ToolErrorCode.BOOK_NOT_FOUND,
        message="Book was not found",
    )
