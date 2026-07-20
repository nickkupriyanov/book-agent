from collections.abc import Sequence
from typing import Protocol

from app.llm.models import Message, ModelResponse
from app.tools.models import ToolDefinition


class LLMProvider(Protocol):
    def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> ModelResponse: ...
