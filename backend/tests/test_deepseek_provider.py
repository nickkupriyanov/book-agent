from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from app.llm.deepseek import DeepSeekProvider
from app.llm.exceptions import (
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.models import Message, MessageRole, ModelResponse, TokenUsage
from app.tools.books import SEARCH_BOOKS_TOOL
from app.tools.models import ToolCall


def make_client(response: object) -> Mock:
    client = Mock()
    client.chat.completions.create.return_value = response
    return client


def test_generate_sends_model_and_messages_to_chat_completions() -> None:
    response = SimpleNamespace(
        id="deepseek-response-1",
        choices=[SimpleNamespace(message=SimpleNamespace(content="Ответ"))],
        usage=None,
    )
    client = make_client(response)
    provider = DeepSeekProvider(client=client, model="test-model")
    messages = [
        Message(role=MessageRole.SYSTEM, content="Системная инструкция"),
        Message(role=MessageRole.USER, content="Расскажи о Дюне"),
        Message(role=MessageRole.ASSISTANT, content="Предыдущий ответ"),
    ]

    provider.generate(messages, tools=())

    client.chat.completions.create.assert_called_once_with(
        model="test-model",
        messages=[
            {"role": "system", "content": "Системная инструкция"},
            {"role": "user", "content": "Расскажи о Дюне"},
            {"role": "assistant", "content": "Предыдущий ответ"},
        ],
    )


def test_generate_sends_tool_definitions_as_json_schema() -> None:
    response = SimpleNamespace(
        id="deepseek-response-1",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="", tool_calls=[])
            )
        ],
        usage=None,
    )
    client = make_client(response)
    provider = DeepSeekProvider(client=client, model="test-model")

    provider.generate(
        [Message(role=MessageRole.USER, content="Найди Дюну")],
        tools=(SEARCH_BOOKS_TOOL,),
    )

    client.chat.completions.create.assert_called_once_with(
        model="test-model",
        messages=[{"role": "user", "content": "Найди Дюну"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": SEARCH_BOOKS_TOOL.name,
                    "description": SEARCH_BOOKS_TOOL.description,
                    "parameters": (
                        SEARCH_BOOKS_TOOL.arguments_model.model_json_schema()
                    ),
                },
            }
        ],
    )


def test_generate_converts_tool_history_to_api_messages() -> None:
    response = SimpleNamespace(
        id="deepseek-response-2",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Готово", tool_calls=[])
            )
        ],
        usage=None,
    )
    client = make_client(response)
    provider = DeepSeekProvider(client=client, model="test-model")
    call = ToolCall(
        id="call-1",
        name="search_books",
        arguments={"query": "Дюна"},
    )

    provider.generate(
        [
            Message(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=[call],
            ),
            Message(
                role=MessageRole.TOOL,
                content='{"books": []}',
                tool_call_id="call-1",
                tool_name="search_books",
            ),
        ],
        tools=(),
    )

    client.chat.completions.create.assert_called_once_with(
        model="test-model",
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "search_books",
                            "arguments": '{"query": "Дюна"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "content": '{"books": []}',
                "tool_call_id": "call-1",
            },
        ],
    )


def test_generate_normalizes_provider_tool_calls() -> None:
    response = SimpleNamespace(
        id="deepseek-response-3",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            type="function",
                            function=SimpleNamespace(
                                name="search_books",
                                arguments='{"query": "Дюна", "limit": 5}',
                            ),
                        )
                    ],
                )
            )
        ],
        usage=None,
    )
    provider = DeepSeekProvider(client=make_client(response), model="test-model")

    result = provider.generate(
        [Message(role=MessageRole.USER, content="Найди Дюну")],
        tools=(SEARCH_BOOKS_TOOL,),
    )

    assert result.text == ""
    assert result.tool_calls == [
        ToolCall(
            id="call-1",
            name="search_books",
            arguments={"query": "Дюна", "limit": 5},
        )
    ]


def test_generate_rejects_invalid_tool_call_arguments() -> None:
    response = SimpleNamespace(
        id="deepseek-response-4",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(
                                name="search_books",
                                arguments="not-json",
                            ),
                        )
                    ],
                )
            )
        ],
        usage=None,
    )
    provider = DeepSeekProvider(client=make_client(response), model="test-model")

    with pytest.raises(LLMProviderError, match="invalid tool call"):
        provider.generate(
            [Message(role=MessageRole.USER, content="Найди Дюну")],
            tools=(SEARCH_BOOKS_TOOL,),
        )


def test_generate_converts_deepseek_response_to_model_response() -> None:
    response = SimpleNamespace(
        id="deepseek-response-1",
        choices=[SimpleNamespace(message=SimpleNamespace(content="Краткий ответ"))],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=7),
    )
    provider = DeepSeekProvider(client=make_client(response), model="test-model")

    result = provider.generate(
        [Message(role=MessageRole.USER, content="Сообщение")],
        tools=(),
    )

    assert result == ModelResponse(
        text="Краткий ответ",
        response_id="deepseek-response-1",
        usage=TokenUsage(input_tokens=12, output_tokens=7),
    )


def test_generate_allows_response_without_usage() -> None:
    response = SimpleNamespace(
        id="deepseek-response-2",
        choices=[SimpleNamespace(message=SimpleNamespace(content="Ответ"))],
        usage=None,
    )
    provider = DeepSeekProvider(client=make_client(response), model="test-model")

    result = provider.generate(
        [Message(role=MessageRole.USER, content="Сообщение")],
        tools=(),
    )

    assert result.usage is None


def test_generate_converts_timeout_error() -> None:
    client = make_client(response=None)
    client.chat.completions.create.side_effect = APITimeoutError(
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    )
    provider = DeepSeekProvider(client=client, model="test-model")

    with pytest.raises(LLMTimeoutError):
        provider.generate(
            [Message(role=MessageRole.USER, content="Сообщение")],
            tools=(),
        )


def test_generate_converts_connection_error() -> None:
    client = make_client(response=None)
    client.chat.completions.create.side_effect = APIConnectionError(
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    )
    provider = DeepSeekProvider(client=client, model="test-model")

    with pytest.raises(LLMUnavailableError):
        provider.generate(
            [Message(role=MessageRole.USER, content="Сообщение")],
            tools=(),
        )


def test_generate_converts_authentication_error() -> None:
    client = make_client(response=None)
    client.chat.completions.create.side_effect = AuthenticationError(
        "Invalid API key",
        response=httpx.Response(
            401,
            request=httpx.Request(
                "POST", "https://api.deepseek.com/chat/completions"
            ),
        ),
        body=None,
    )
    provider = DeepSeekProvider(client=client, model="test-model")

    with pytest.raises(LLMUnavailableError):
        provider.generate(
            [Message(role=MessageRole.USER, content="Сообщение")],
            tools=(),
        )


def test_generate_converts_rate_limit_error() -> None:
    client = make_client(response=None)
    client.chat.completions.create.side_effect = RateLimitError(
        "Rate limit exceeded",
        response=httpx.Response(
            429,
            request=httpx.Request(
                "POST", "https://api.deepseek.com/chat/completions"
            ),
        ),
        body=None,
    )
    provider = DeepSeekProvider(client=client, model="test-model")

    with pytest.raises(LLMRateLimitError):
        provider.generate(
            [Message(role=MessageRole.USER, content="Сообщение")],
            tools=(),
        )


def test_generate_converts_other_api_status_error() -> None:
    client = make_client(response=None)
    client.chat.completions.create.side_effect = APIStatusError(
        "Internal provider details",
        response=httpx.Response(
            500,
            request=httpx.Request(
                "POST", "https://api.deepseek.com/chat/completions"
            ),
        ),
        body=None,
    )
    provider = DeepSeekProvider(client=client, model="test-model")

    with pytest.raises(LLMProviderError):
        provider.generate(
            [Message(role=MessageRole.USER, content="Сообщение")],
            tools=(),
        )
