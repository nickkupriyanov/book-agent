from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.tools.books import (
    SEARCH_BOOKS_TOOL,
    SearchBooksArguments,
    SearchBooksResult,
)
from app.tools.registry import (
    DuplicateToolError,
    ToolRegistry,
    UnknownToolError,
)


def test_registry_exposes_registered_definitions() -> None:
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, Mock())

    assert registry.definitions() == (SEARCH_BOOKS_TOOL,)


def test_registry_validates_arguments_and_calls_handler() -> None:
    handler = Mock(return_value=SearchBooksResult(books=[]))
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, handler)

    result = registry.execute(
        name="search_books",
        raw_arguments={"query": "Дюна", "limit": 5},
    )

    handler.assert_called_once_with(SearchBooksArguments(query="Дюна", limit=5))
    assert result == SearchBooksResult(books=[])


def test_registry_rejects_invalid_arguments_before_handler() -> None:
    handler = Mock(return_value=SearchBooksResult(books=[]))
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, handler)

    with pytest.raises(ValidationError):
        registry.execute(
            name="search_books",
            raw_arguments={"query": "Дюна", "sql": "DROP TABLE books"},
        )

    handler.assert_not_called()


def test_registry_rejects_unknown_tool() -> None:
    registry = ToolRegistry()

    with pytest.raises(UnknownToolError, match="Unknown tool: execute_sql"):
        registry.execute(
            name="execute_sql",
            raw_arguments={"query": "DROP TABLE books"},
        )


def test_registry_rejects_duplicate_name() -> None:
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, Mock())

    with pytest.raises(DuplicateToolError, match="Tool already registered: search_books"):
        registry.register(SEARCH_BOOKS_TOOL, Mock())


def test_registry_validates_handler_result() -> None:
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, Mock(return_value={"unexpected": True}))

    with pytest.raises(ValidationError):
        registry.execute(
            name="search_books",
            raw_arguments={"query": "Дюна"},
        )
