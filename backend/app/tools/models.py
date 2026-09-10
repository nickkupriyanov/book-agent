from dataclasses import dataclass
from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolAccess(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


class ToolErrorCode(str, Enum):
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGUMENTS = "invalid_arguments"
    INVALID_RESULT = "invalid_result"
    BOOK_NOT_FOUND = "book_not_found"
    BOOK_ALREADY_IN_LIBRARY = "book_already_in_library"
    LIBRARY_ENTRY_NOT_FOUND = "library_entry_not_found"
    AMBIGUOUS_APPROVAL_BATCH = "ambiguous_approval_batch"
    USER_REJECTED = "user_rejected"
    CATALOG_UNAVAILABLE = "catalog_unavailable"


class ToolCall(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, object]

    model_config = ConfigDict(extra="forbid")


class ToolError(BaseModel):
    code: ToolErrorCode
    message: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class ToolResult(BaseModel):
    tool_call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    output: dict[str, object] | None = None
    error: ToolError | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_output_or_error(self) -> Self:
        if (self.output is None) == (self.error is None):
            raise ValueError("ToolResult requires exactly one of output or error")
        return self


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    access: ToolAccess
    arguments_model: type[BaseModel]
    result_model: type[BaseModel]
