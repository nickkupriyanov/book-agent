from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.exceptions import (
    BookNotFoundError,
    DuplicateLibraryEntryError,
    LibraryEntryNotFoundError,
)
from app.models import ReadingStatus
from app.service import BookService
from app.tools.books import BookToolResult
from app.tools.exceptions import ToolExecutionError
from app.tools.models import ToolAccess, ToolDefinition, ToolErrorCode


class GetUserLibraryArguments(BaseModel):
    status: ReadingStatus | None = None
    limit: int | None = Field(default=None, ge=1, le=50)
    recent_first: bool = False

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
            limit=arguments.limit,
            recent_first=arguments.recent_first,
        )
        return GetUserLibraryResult(
            entries=[
                LibraryEntryToolResult.model_validate(entry) for entry in entries
            ]
        )


class AddBookArguments(BaseModel):
    book_id: UUID
    status: ReadingStatus

    model_config = ConfigDict(extra="forbid")


class AddBookResult(BaseModel):
    entry: LibraryEntryToolResult
    changed: bool

    model_config = ConfigDict(extra="forbid")


class AddBookHandler:
    def __init__(self, service: BookService, user_id: UUID) -> None:
        self._service = service
        self._user_id = user_id

    def __call__(self, arguments: AddBookArguments) -> AddBookResult:
        changed = True
        try:
            entry = self._service.add_book(
                user_id=self._user_id,
                book_id=arguments.book_id,
                status=arguments.status,
            )
        except BookNotFoundError as exc:
            raise ToolExecutionError(
                code=ToolErrorCode.BOOK_NOT_FOUND,
                message="Book was not found",
            ) from exc
        except DuplicateLibraryEntryError:
            entry = self._service.get_library_entry(
                user_id=self._user_id,
                book_id=arguments.book_id,
            )
            if entry.status != arguments.status:
                raise ToolExecutionError(
                    code=ToolErrorCode.BOOK_ALREADY_IN_LIBRARY,
                    message=(
                        "Book is already in the library with a different "
                        "reading status"
                    ),
                )
            changed = False

        return AddBookResult(
            entry=LibraryEntryToolResult.model_validate(entry),
            changed=changed,
        )


class UpdateBookStatusArguments(BaseModel):
    book_id: UUID
    status: ReadingStatus

    model_config = ConfigDict(extra="forbid")


class UpdateBookStatusResult(BaseModel):
    entry: LibraryEntryToolResult

    model_config = ConfigDict(extra="forbid")


class UpdateBookStatusHandler:
    def __init__(self, service: BookService, user_id: UUID) -> None:
        self._service = service
        self._user_id = user_id

    def __call__(
        self,
        arguments: UpdateBookStatusArguments,
    ) -> UpdateBookStatusResult:
        try:
            entry = self._service.update_status(
                user_id=self._user_id,
                book_id=arguments.book_id,
                status=arguments.status,
            )
        except LibraryEntryNotFoundError as exc:
            raise ToolExecutionError(
                code=ToolErrorCode.LIBRARY_ENTRY_NOT_FOUND,
                message="Book is not in the library",
            ) from exc

        return UpdateBookStatusResult(
            entry=LibraryEntryToolResult.model_validate(entry)
        )


class RemoveBookArguments(BaseModel):
    book_id: UUID

    model_config = ConfigDict(extra="forbid")


class RemoveBookResult(BaseModel):
    book_id: UUID
    title: str
    author: str
    status: ReadingStatus

    model_config = ConfigDict(extra="forbid")


class RemoveBookHandler:
    def __init__(
        self,
        service: BookService,
        user_id: UUID,
        *,
        commit: bool = True,
    ) -> None:
        self._service = service
        self._user_id = user_id
        self._commit = commit

    def __call__(self, arguments: RemoveBookArguments) -> RemoveBookResult:
        try:
            if self._commit:
                entry = self._service.remove_book(
                    user_id=self._user_id,
                    book_id=arguments.book_id,
                )
            else:
                entry = self._service.remove_book(
                    user_id=self._user_id,
                    book_id=arguments.book_id,
                    commit=False,
                )
        except LibraryEntryNotFoundError as exc:
            raise ToolExecutionError(
                code=ToolErrorCode.LIBRARY_ENTRY_NOT_FOUND,
                message="Book is not in the library",
            ) from exc

        return RemoveBookResult(
            book_id=entry.book_id,
            title=entry.book.title,
            author=entry.book.author,
            status=entry.status,
        )


class RemoveBookApprovalSummary:
    def __init__(self, service: BookService, user_id: UUID) -> None:
        self._service = service
        self._user_id = user_id

    def __call__(self, arguments: RemoveBookArguments) -> str:
        try:
            entry = self._service.get_library_entry(
                user_id=self._user_id,
                book_id=arguments.book_id,
            )
        except LibraryEntryNotFoundError as exc:
            raise ToolExecutionError(
                code=ToolErrorCode.LIBRARY_ENTRY_NOT_FOUND,
                message="Book is not in the library",
            ) from exc

        return (
            f"Удалить «{entry.book.title}» ({entry.book.author}) "
            "из вашей библиотеки."
        )


GET_USER_LIBRARY_TOOL = ToolDefinition(
    name="get_user_library",
    description=(
        "Get books from the current user's library, optionally filtered "
        "by reading status. To get recently finished books, use "
        "status='finished', recent_first=true, and a limit."
    ),
    access=ToolAccess.READ,
    arguments_model=GetUserLibraryArguments,
    result_model=GetUserLibraryResult,
)


ADD_BOOK_TOOL = ToolDefinition(
    name="add_book",
    description=(
        "Add a book to the current user's library with a reading status. "
        "Repeating the same book and status is a successful no-op."
    ),
    access=ToolAccess.WRITE,
    arguments_model=AddBookArguments,
    result_model=AddBookResult,
)


UPDATE_BOOK_STATUS_TOOL = ToolDefinition(
    name="update_book_status",
    description="Update a book's reading status in the current user's library.",
    access=ToolAccess.WRITE,
    arguments_model=UpdateBookStatusArguments,
    result_model=UpdateBookStatusResult,
)


REMOVE_BOOK_TOOL = ToolDefinition(
    name="remove_book",
    description="Remove a book from the current user's library.",
    access=ToolAccess.DESTRUCTIVE,
    arguments_model=RemoveBookArguments,
    result_model=RemoveBookResult,
)
