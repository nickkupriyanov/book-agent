from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.tools.models import ToolAccess, ToolDefinition


class SearchBooksArguments(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=50)

    model_config = ConfigDict(extra="forbid")


class BookToolResult(BaseModel):
    id: UUID
    title: str
    author: str

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class SearchBooksResult(BaseModel):
    books: list[BookToolResult]

    model_config = ConfigDict(extra="forbid")


SEARCH_BOOKS_TOOL = ToolDefinition(
    name="search_books",
    description="Search the local book catalog by title.",
    access=ToolAccess.READ,
    arguments_model=SearchBooksArguments,
    result_model=SearchBooksResult,
)
