from collections import deque
from collections.abc import Sequence

from app.llm.models import Message, ModelResponse
from app.tools.models import ToolDefinition


class FakeLLMProvider:
    def __init__(self, responses: Sequence[ModelResponse]) -> None:
        self._responses = deque(responses)
        self.calls: list[list[Message]] = []
        self.tools_by_call: list[tuple[ToolDefinition, ...]] = []

    def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> ModelResponse:
        self.calls.append(list(messages))
        self.tools_by_call.append(tuple(tools))
        if not self._responses:
            raise RuntimeError("No fake responses remaining")
        return self._responses.popleft()
