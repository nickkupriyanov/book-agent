from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import ReadingStatus
from app.service import BookService
from app.tools.books import BookToolResult
from app.tools.models import ToolAccess, ToolDefinition


class GetUserLibraryArguments(BaseModel):
    status: ReadingStatus | None = None

    model_config = ConfigDict(extra="forbid")


class LibraryEntryToolResult(BaseModel):
    book: BookToolResult
    status: ReadingStatus

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class GetUserLibraryResult(BaseModel):
    entries: list[LibraryEntryToolResult]

    model_config = ConfigDict(extra="forbid")


class GetUserLibraryHandler:
    def __init__(self, service: BookService, user_id: UUID) -> None:
        self._service = service
        self._user_id = user_id

    def __call__(
        self,
        arguments: GetUserLibraryArguments,
    ) -> GetUserLibraryResult:
        entries = self._service.get_library(
            user_id=self._user_id,
            status=arguments.status,
        )
        return GetUserLibraryResult(
            entries=[
                LibraryEntryToolResult.model_validate(entry) for entry in entries
            ]
        )


GET_USER_LIBRARY_TOOL = ToolDefinition(
    name="get_user_library",
    description=(
        "Get books from the current user's library, optionally filtered "
        "by reading status."
    ),
    access=ToolAccess.READ,
    arguments_model=GetUserLibraryArguments,
    result_model=GetUserLibraryResult,
)
