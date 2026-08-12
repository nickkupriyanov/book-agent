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
ToolApprovalSummary = Callable[[BaseModel], str]


class DuplicateToolError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Tool already registered: {name}")


@dataclass(frozen=True)
class _RegisteredTool:
    definition: ToolDefinition
    handler: ToolHandler
    approval_summary: ToolApprovalSummary | None


@dataclass(frozen=True)
class PreparedToolCall:
    tool_call_id: str
    _tool: _RegisteredTool
    arguments: BaseModel

    @property
    def definition(self) -> ToolDefinition:
        return self._tool.definition

    @property
    def canonical_arguments(self) -> dict[str, object]:
        return self.arguments.model_dump(mode="json")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, _RegisteredTool] = {}

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
        *,
        approval_summary: ToolApprovalSummary | None = None,
    ) -> None:
        if definition.name in self._tools:
            raise DuplicateToolError(definition.name)
        self._tools[definition.name] = _RegisteredTool(
            definition,
            handler,
            approval_summary,
        )

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(tool.definition for tool in self._tools.values())

    def get_definition(self, name: str) -> ToolDefinition | None:
        tool = self._tools.get(name)
        return None if tool is None else tool.definition

    def prepare(
        self,
        call: ToolCall,
    ) -> PreparedToolCall | ToolResult:
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

        return PreparedToolCall(
            tool_call_id=call.id,
            _tool=tool,
            arguments=arguments,
        )

    def execute_prepared(self, call: PreparedToolCall) -> ToolResult:
        try:
            raw_result = call._tool.handler(call.arguments)
        except ToolExecutionError as exc:
            return ToolResult(
                tool_call_id=call.tool_call_id,
                tool_name=call.definition.name,
                error=ToolError(code=exc.code, message=exc.message),
            )

        try:
            result = call.definition.result_model.model_validate(raw_result)
        except ValidationError:
            return ToolResult(
                tool_call_id=call.tool_call_id,
                tool_name=call.definition.name,
                error=ToolError(
                    code=ToolErrorCode.INVALID_RESULT,
                    message="Tool returned an invalid result",
                ),
            )

        return ToolResult(
            tool_call_id=call.tool_call_id,
            tool_name=call.definition.name,
            output=result.model_dump(mode="json"),
        )

    def summarize_for_approval(
        self,
        call: PreparedToolCall,
    ) -> str | ToolResult:
        summary_builder = call._tool.approval_summary
        if summary_builder is None:
            raise RuntimeError(
                f"Tool has no approval summary builder: {call.definition.name}"
            )

        try:
            return summary_builder(call.arguments)
        except ToolExecutionError as exc:
            return ToolResult(
                tool_call_id=call.tool_call_id,
                tool_name=call.definition.name,
                error=ToolError(code=exc.code, message=exc.message),
            )

    def execute(
        self,
        call: ToolCall,
    ) -> ToolResult:
        prepared = self.prepare(call)
        if isinstance(prepared, ToolResult):
            return prepared
        return self.execute_prepared(prepared)
