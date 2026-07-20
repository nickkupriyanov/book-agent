from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tools.models import ToolCall


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    role: MessageRole
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_role_fields(self) -> Self:
        if self.role is MessageRole.TOOL:
            if self.tool_calls or not self.tool_call_id or not self.tool_name:
                raise ValueError(
                    "Tool messages require tool_call_id and tool_name only"
                )
        elif self.tool_call_id is not None or self.tool_name is not None:
            raise ValueError("Only tool messages may reference a tool call")
        elif self.role is not MessageRole.ASSISTANT and self.tool_calls:
            raise ValueError("Only assistant messages may contain tool calls")
        return self


class TokenUsage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class ModelResponse(BaseModel):
    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    response_id: str | None = None
    usage: TokenUsage | None = None
