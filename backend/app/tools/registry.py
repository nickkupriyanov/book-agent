from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.tools.exceptions import ToolExecutionError
from app.tools.models import (
    ToolCall,
    ToolDefinition,
    ToolError,
    ToolErrorCode,
    ToolResult,
)

ToolHandler = Callable[..., BaseModel]


class DuplicateToolError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Tool already registered: {name}")


@dataclass(frozen=True)
class _RegisteredTool:
    definition: ToolDefinition
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, _RegisteredTool] = {}

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
    ) -> None:
        if definition.name in self._tools:
            raise DuplicateToolError(definition.name)
        self._tools[definition.name] = _RegisteredTool(definition, handler)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(tool.definition for tool in self._tools.values())

    def execute(
        self,
        call: ToolCall,
    ) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                error=ToolError(
                    code=ToolErrorCode.UNKNOWN_TOOL,
                    message="Tool is not available",
                ),
            )

        try:
            arguments = tool.definition.arguments_model.model_validate(call.arguments)
        except ValidationError:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                error=ToolError(
                    code=ToolErrorCode.INVALID_ARGUMENTS,
                    message="Tool arguments are invalid",
                ),
            )

        try:
            raw_result = tool.handler(arguments)
        except ToolExecutionError as exc:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                error=ToolError(code=exc.code, message=exc.message),
            )

        try:
            result = tool.definition.result_model.model_validate(raw_result)
        except ValidationError:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                error=ToolError(
                    code=ToolErrorCode.INVALID_RESULT,
                    message="Tool returned an invalid result",
                ),
            )

        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            output=result.model_dump(mode="json"),
        )
