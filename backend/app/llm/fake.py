from collections import deque
from collections.abc import Sequence

from app.llm.models import Message, ModelResponse


class FakeLLMProvider:
    def __init__(self, responses: Sequence[ModelResponse]) -> None:
        self._responses = deque(responses)
        self.calls: list[list[Message]] = []

    def generate(self, messages: Sequence[Message]) -> ModelResponse:
        self.calls.append(list(messages))
        if not self._responses:
            raise RuntimeError("No fake responses remaining")
        return self._responses.popleft()
