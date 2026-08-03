from unittest.mock import create_autospec
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.exceptions import BookNotFoundError
from app.models import Book, ReadingStatus
from app.repository import BookRepository
from app.service import BookService, RecommendationCandidate
from app.tools.models import ToolAccess, ToolCall, ToolErrorCode
from app.tools.recommendations import (
    FIND_SIMILAR_BOOKS_TOOL,
    FindSimilarBooksArguments,
    FindSimilarBooksHandler,
    FindSimilarBooksResult,
    RecommendationToolResult,
)
from app.tools.registry import ToolRegistry

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")
NINETEEN_EIGHTY_FOUR_ID = UUID("10000000-0000-0000-0000-000000000002")
ATOMIC_HABITS_ID = UUID("10000000-0000-0000-0000-000000000004")
FLOWERS_FOR_ALGERNON_ID = UUID("10000000-0000-0000-0000-000000000007")
LEFT_HAND_OF_DARKNESS_ID = UUID("10000000-0000-0000-0000-000000000008")
SAPIENS_ID = UUID("10000000-0000-0000-0000-000000000010")


def test_definition_publishes_strict_read_tool_without_user_id() -> None:
    schema = FIND_SIMILAR_BOOKS_TOOL.arguments_model.model_json_schema()

    assert FIND_SIMILAR_BOOKS_TOOL.name == "find_similar_books"
    assert FIND_SIMILAR_BOOKS_TOOL.access is ToolAccess.READ
    assert FIND_SIMILAR_BOOKS_TOOL.arguments_model is FindSimilarBooksArguments
    assert FIND_SIMILAR_BOOKS_TOOL.result_model is FindSimilarBooksResult
    assert "excluded automatically" in FIND_SIMILAR_BOOKS_TOOL.description
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["source_book_ids"]
    assert schema["properties"]["source_book_ids"]["minItems"] == 1
    assert schema["properties"]["source_book_ids"]["uniqueItems"] is True
    assert "user_id" not in schema["properties"]


def test_arguments_validate_sources_limit_duplicates_and_extra_fields() -> None:
    arguments = FindSimilarBooksArguments(
        source_book_ids=[DUNE_ID],
    )

    assert arguments.source_book_ids == [DUNE_ID]
    assert arguments.limit == 3

    invalid_arguments = (
        {"source_book_ids": []},
        {"source_book_ids": [str(DUNE_ID), str(DUNE_ID)]},
        {"source_book_ids": ["not-a-uuid"]},
        {"source_book_ids": [str(DUNE_ID)], "limit": 0},
        {"source_book_ids": [str(DUNE_ID)], "limit": 11},
        {
            "source_book_ids": [str(DUNE_ID)],
            "user_id": str(USER_ID),
        },
    )
    for invalid_argument in invalid_arguments:
        with pytest.raises(ValidationError):
            FindSimilarBooksArguments.model_validate(invalid_argument)


def test_handler_scopes_user_and_converts_domain_candidate() -> None:
    service = create_autospec(BookService, instance=True)
    book = Book(
        id=LEFT_HAND_OF_DARKNESS_ID,
        title="Левая рука Тьмы",
        author="Урсула Ле Гуин",
        tags=["politics", "science_fiction", "sociology"],
    )
    service.find_similar_books.return_value = [
        RecommendationCandidate(
            book=book,
            matched_tags=("politics", "science_fiction"),
            score=2,
        )
    ]
    handler = FindSimilarBooksHandler(service, USER_ID)
    arguments = FindSimilarBooksArguments(
        source_book_ids=[DUNE_ID],
        limit=2,
    )

    result = handler(arguments)

    service.find_similar_books.assert_called_once_with(
        user_id=USER_ID,
        source_book_ids=[DUNE_ID],
        limit=2,
    )
    assert result == FindSimilarBooksResult(
        recommendations=[
            RecommendationToolResult(
                book={
                    "id": LEFT_HAND_OF_DARKNESS_ID,
                    "title": "Левая рука Тьмы",
                    "author": "Урсула Ле Гуин",
                    "tags": ["politics", "science_fiction", "sociology"],
                },
                matched_tags=["politics", "science_fiction"],
                score=2,
            )
        ]
    )


def test_registry_returns_structured_recommendations(session: Session) -> None:
    service = BookService(BookRepository(session))
    registry = ToolRegistry()
    registry.register(
        FIND_SIMILAR_BOOKS_TOOL,
        FindSimilarBooksHandler(service, USER_ID),
    )

    result = registry.execute(
        ToolCall(
            id="recommend-1",
            name="find_similar_books",
            arguments={"source_book_ids": [str(DUNE_ID)], "limit": 2},
        )
    )

    assert result.error is None
    assert result.output == {
        "recommendations": [
            {
                "book": {
                    "id": str(LEFT_HAND_OF_DARKNESS_ID),
                    "title": "Левая рука Тьмы",
                    "author": "Урсула Ле Гуин",
                    "tags": ["politics", "science_fiction", "sociology"],
                },
                "matched_tags": ["politics", "science_fiction"],
                "score": 2,
            },
            {
                "book": {
                    "id": str(NINETEEN_EIGHTY_FOUR_ID),
                    "title": "1984",
                    "author": "Джордж Оруэлл",
                    "tags": ["classic", "dystopia", "politics"],
                },
                "matched_tags": ["politics"],
                "score": 1,
            },
        ]
    }


@pytest.mark.parametrize(
    "source_book_ids",
    ([], [str(DUNE_ID), str(DUNE_ID)]),
)
def test_registry_rejects_invalid_arguments_before_handler(
    source_book_ids: list[str],
) -> None:
    service = create_autospec(BookService, instance=True)
    registry = ToolRegistry()
    registry.register(
        FIND_SIMILAR_BOOKS_TOOL,
        FindSimilarBooksHandler(service, USER_ID),
    )

    result = registry.execute(
        ToolCall(
            id="recommend-invalid",
            name="find_similar_books",
            arguments={"source_book_ids": source_book_ids},
        )
    )

    service.find_similar_books.assert_not_called()
    assert result.output is None
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGUMENTS


def test_unknown_source_is_returned_as_safe_tool_error() -> None:
    service = create_autospec(BookService, instance=True)
    service.find_similar_books.side_effect = BookNotFoundError(uuid4())
    registry = ToolRegistry()
    registry.register(
        FIND_SIMILAR_BOOKS_TOOL,
        FindSimilarBooksHandler(service, USER_ID),
    )

    result = registry.execute(
        ToolCall(
            id="recommend-missing",
            name="find_similar_books",
            arguments={"source_book_ids": [str(uuid4())]},
        )
    )

    assert result.output is None
    assert result.error is not None
    assert result.error.code is ToolErrorCode.BOOK_NOT_FOUND
    assert result.error.message == "Source book was not found"


def test_empty_recommendations_are_a_successful_result(session: Session) -> None:
    service = BookService(BookRepository(session))
    service.add_book(
        USER_ID,
        FLOWERS_FOR_ALGERNON_ID,
        ReadingStatus.WANT_TO_READ,
    )
    service.add_book(
        USER_ID,
        SAPIENS_ID,
        ReadingStatus.FINISHED,
    )
    registry = ToolRegistry()
    registry.register(
        FIND_SIMILAR_BOOKS_TOOL,
        FindSimilarBooksHandler(service, USER_ID),
    )

    result = registry.execute(
        ToolCall(
            id="recommend-empty",
            name="find_similar_books",
            arguments={"source_book_ids": [str(ATOMIC_HABITS_ID)]},
        )
    )

    assert result.error is None
    assert result.output == {"recommendations": []}
