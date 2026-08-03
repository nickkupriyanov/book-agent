from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.exceptions import BookNotFoundError
from app.service import BookService
from app.tools.books import BookToolResult
from app.tools.exceptions import ToolExecutionError
from app.tools.models import ToolAccess, ToolDefinition, ToolErrorCode


class FindSimilarBooksArguments(BaseModel):
    source_book_ids: list[UUID] = Field(
        min_length=1,
        json_schema_extra={"uniqueItems": True},
    )
    limit: int = Field(default=3, ge=1, le=10)

    model_config = ConfigDict(extra="forbid")

    @field_validator("source_book_ids")
    @classmethod
    def reject_duplicate_source_ids(cls, book_ids: list[UUID]) -> list[UUID]:
        if len(book_ids) != len(set(book_ids)):
            raise ValueError("source_book_ids must be unique")
        return book_ids


class RecommendationToolResult(BaseModel):
    book: BookToolResult
    matched_tags: list[str]
    score: int = Field(ge=1)

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class FindSimilarBooksResult(BaseModel):
    recommendations: list[RecommendationToolResult]

    model_config = ConfigDict(extra="forbid")


class FindSimilarBooksHandler:
    def __init__(self, service: BookService, user_id: UUID) -> None:
        self._service = service
        self._user_id = user_id

    def __call__(
        self,
        arguments: FindSimilarBooksArguments,
    ) -> FindSimilarBooksResult:
        try:
            candidates = self._service.find_similar_books(
                user_id=self._user_id,
                source_book_ids=arguments.source_book_ids,
                limit=arguments.limit,
            )
        except BookNotFoundError as exc:
            raise ToolExecutionError(
                code=ToolErrorCode.BOOK_NOT_FOUND,
                message="Source book was not found",
            ) from exc

        return FindSimilarBooksResult(
            recommendations=[
                RecommendationToolResult.model_validate(candidate)
                for candidate in candidates
            ]
        )


FIND_SIMILAR_BOOKS_TOOL = ToolDefinition(
    name="find_similar_books",
    description=(
        "Find books similar to catalog books by tags. Books already in the "
        "current user's library are excluded automatically."
    ),
    access=ToolAccess.READ,
    arguments_model=FindSimilarBooksArguments,
    result_model=FindSimilarBooksResult,
)
