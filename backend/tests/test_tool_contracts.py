import pytest
from pydantic import ValidationError

from app.tools.books import (
    SEARCH_BOOKS_TOOL,
    BookToolResult,
    SearchBooksArguments,
    SearchBooksResult,
)
from app.tools.models import ToolAccess


def test_search_books_definition_describes_read_tool() -> None:
    assert SEARCH_BOOKS_TOOL.name == "search_books"
    assert SEARCH_BOOKS_TOOL.description == "Search the local book catalog by title."
    assert SEARCH_BOOKS_TOOL.access is ToolAccess.READ
    assert SEARCH_BOOKS_TOOL.arguments_model is SearchBooksArguments
    assert SEARCH_BOOKS_TOOL.result_model is SearchBooksResult


def test_search_books_arguments_accept_valid_values() -> None:
    arguments = SearchBooksArguments(query="Дюна", limit=10)

    assert arguments.query == "Дюна"
    assert arguments.limit == 10


def test_search_books_arguments_use_default_limit() -> None:
    arguments = SearchBooksArguments(query="Дюна")

    assert arguments.limit == 20


def test_search_books_arguments_reject_empty_query() -> None:
    with pytest.raises(ValidationError):
        SearchBooksArguments.model_validate({"query": ""})


def test_search_books_arguments_reject_out_of_range_limit() -> None:
    for invalid_limit in (0, 51):
        with pytest.raises(ValidationError):
            SearchBooksArguments.model_validate(
                {"query": "Дюна", "limit": invalid_limit}
            )


def test_search_books_arguments_reject_extra_fields_and_publish_strict_schema() -> None:
    with pytest.raises(ValidationError):
        SearchBooksArguments.model_validate(
            {"query": "Дюна", "sql": "DROP TABLE books"}
        )

    schema = SEARCH_BOOKS_TOOL.arguments_model.model_json_schema()
    properties = schema["properties"]

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["query"]
    assert properties["query"]["minLength"] == 1
    assert properties["limit"] == {
        "default": 20,
        "maximum": 50,
        "minimum": 1,
        "title": "Limit",
        "type": "integer",
    }


def test_search_books_result_has_structured_book_list() -> None:
    schema = SEARCH_BOOKS_TOOL.result_model.model_json_schema()

    assert schema["properties"]["books"]["type"] == "array"
    assert schema["$defs"]["BookToolResult"] == BookToolResult.model_json_schema()
