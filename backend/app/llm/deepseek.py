from collections.abc import Sequence
from typing import assert_never

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)
from openai.types.chat import ChatCompletionMessageParam

from app.llm.exceptions import (
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.models import Message, MessageRole, ModelResponse, TokenUsage
from app.tools.models import ToolDefinition


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

    def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> ModelResponse:
        if tools:
            raise NotImplementedError("DeepSeek tool calling is not implemented yet")
        api_messages: list[ChatCompletionMessageParam] = [
            _to_api_message(message) for message in messages
        ]
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=api_messages,
            )
        except APITimeoutError as exc:
            raise LLMTimeoutError from exc
        except APIConnectionError as exc:
            raise LLMUnavailableError from exc
        except AuthenticationError as exc:
            raise LLMUnavailableError from exc
        except RateLimitError as exc:
            raise LLMRateLimitError from exc
        except APIStatusError as exc:
            raise LLMProviderError from exc

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
