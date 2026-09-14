from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.memory.service import MemoryService
from app.tools.models import ToolAccess, ToolDefinition


class SearchUserNotesArguments(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)

    model_config = ConfigDict(extra="forbid")


class NoteCitationToolResult(BaseModel):
    chunk_id: UUID
    note_id: UUID
    book_id: UUID | None
    fragment: str
    score: float = Field(gt=0, le=1)

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class SearchUserNotesResult(BaseModel):
    citations: list[NoteCitationToolResult]

    model_config = ConfigDict(extra="forbid")


class SearchUserNotesHandler:
    def __init__(self, service: MemoryService, user_id: UUID) -> None:
        self._service = service
        self._user_id = user_id

    def __call__(
        self,
        arguments: SearchUserNotesArguments,
    ) -> SearchUserNotesResult:
        return SearchUserNotesResult(
            citations=[
                NoteCitationToolResult.model_validate(hit)
                for hit in self._service.search_notes(
                    self._user_id,
                    arguments.query,
                    arguments.limit,
                )
            ]
        )


SEARCH_USER_NOTES_TOOL = ToolDefinition(
    name="search_user_notes",
    description=(
        "Search the current user's personal book notes. Use only when the "
        "request asks about the user's notes, observations, or reading themes. "
        "An empty citations list means the notes do not contain supporting "
        "context."
    ),
    access=ToolAccess.READ,
    arguments_model=SearchUserNotesArguments,
    result_model=SearchUserNotesResult,
)
