from collections.abc import Sequence
from typing import assert_never

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.llm.models import Message, MessageRole, ModelResponse, TokenUsage


def _to_api_message(message: Message) -> ChatCompletionMessageParam:
    match message.role:
        case MessageRole.SYSTEM:
            return {"role": "system", "content": message.content}
        case MessageRole.USER:
            return {"role": "user", "content": message.content}
        case MessageRole.ASSISTANT:
            return {"role": "assistant", "content": message.content}
        case _:
            assert_never(message.role)


class DeepSeekProvider:
    def __init__(self, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def generate(self, messages: Sequence[Message]) -> ModelResponse:
        api_messages: list[ChatCompletionMessageParam] = [
            _to_api_message(message) for message in messages
        ]
        response = self._client.chat.completions.create(
            model=self._model,
            messages=api_messages,
        )

        usage = None
        if response.usage is not None:
            usage = TokenUsage(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
            )

        return ModelResponse(
            text=response.choices[0].message.content or "",
            response_id=response.id,
            usage=usage,
        )
