from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.tools.models import ToolDefinition

ToolHandler = Callable[..., BaseModel]


class UnknownToolError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Unknown tool: {name}")


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
        name: str,
        raw_arguments: dict[str, object],
    ) -> BaseModel:
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownToolError(name)

        arguments = tool.definition.arguments_model.model_validate(raw_arguments)
        raw_result = tool.handler(arguments)
        return tool.definition.result_model.model_validate(raw_result)
