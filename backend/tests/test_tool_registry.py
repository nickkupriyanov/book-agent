from unittest.mock import Mock
from uuid import UUID

import pytest

from app.tools.books import (
    SEARCH_BOOKS_TOOL,
    BookToolResult,
    SearchBooksArguments,
    SearchBooksResult,
)
from app.tools.models import (
    ToolCall,
    ToolError,
    ToolErrorCode,
)
from app.tools.registry import DuplicateToolError, ToolRegistry

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
            }
        ]
    }
    assert result.error is None


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
