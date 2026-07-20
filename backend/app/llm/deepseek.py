import json
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
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionToolParam,
)
from pydantic import ValidationError

from app.llm.exceptions import (
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.models import Message, MessageRole, ModelResponse, TokenUsage
from app.tools.models import ToolCall, ToolDefinition


def _to_api_tool_call(call: ToolCall) -> ChatCompletionMessageToolCallParam:
    return {
        "id": call.id,
        "type": "function",
        "function": {
            "name": call.name,
            "arguments": json.dumps(call.arguments, ensure_ascii=False),
        },
    }


def _to_api_message(message: Message) -> ChatCompletionMessageParam:
    match message.role:
        case MessageRole.SYSTEM:
            return {"role": "system", "content": message.content}
        case MessageRole.USER:
            return {"role": "user", "content": message.content}
        case MessageRole.ASSISTANT:
            if message.tool_calls:
                return {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        _to_api_tool_call(call) for call in message.tool_calls
                    ],
                }
            return {"role": "assistant", "content": message.content}
        case MessageRole.TOOL:
            if message.tool_call_id is None:
                raise ValueError("Tool message is missing tool_call_id")
            return {
                "role": "tool",
                "content": message.content,
                "tool_call_id": message.tool_call_id,
            }
        case _:
            assert_never(message.role)


def _to_api_tool(definition: ToolDefinition) -> ChatCompletionToolParam:
    return {
        "type": "function",
        "function": {
            "name": definition.name,
            "description": definition.description,
            "parameters": definition.arguments_model.model_json_schema(),
        },
    }


def _parse_tool_call(raw_call: object) -> ToolCall:
    try:
        function = getattr(raw_call, "function")
        arguments = json.loads(getattr(function, "arguments"))
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        return ToolCall(
            id=getattr(raw_call, "id"),
            name=getattr(function, "name"),
            arguments=arguments,
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise LLMProviderError("Provider returned an invalid tool call") from exc


class DeepSeekProvider:
    def __init__(self, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> ModelResponse:
        api_messages: list[ChatCompletionMessageParam] = [
            _to_api_message(message) for message in messages
        ]
        try:
            if tools:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=api_messages,
                    tools=[_to_api_tool(tool) for tool in tools],
                )
            else:
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

        response_message = response.choices[0].message
        tool_calls = [
            _parse_tool_call(call)
            for call in (getattr(response_message, "tool_calls", None) or [])
        ]

        return ModelResponse(
            text=response_message.content or "",
            tool_calls=tool_calls,
            response_id=response.id,
            usage=usage,
        )
