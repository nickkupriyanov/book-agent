from collections.abc import Sequence
from typing import Protocol

from app.llm.models import Message, ModelResponse


class LLMProvider(Protocol):
    def generate(self, messages: Sequence[Message]) -> ModelResponse: ...
