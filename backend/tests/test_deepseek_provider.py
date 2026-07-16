from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError

from app.llm.deepseek import DeepSeekProvider
from app.llm.exceptions import LLMTimeoutError, LLMUnavailableError
from app.llm.models import Message, MessageRole, ModelResponse, TokenUsage


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

    provider.generate(messages)

    client.chat.completions.create.assert_called_once_with(
        model="test-model",
        messages=[
            {"role": "system", "content": "Системная инструкция"},
            {"role": "user", "content": "Расскажи о Дюне"},
            {"role": "assistant", "content": "Предыдущий ответ"},
        ],
    )


def test_generate_converts_deepseek_response_to_model_response() -> None:
    response = SimpleNamespace(
        id="deepseek-response-1",
        choices=[SimpleNamespace(message=SimpleNamespace(content="Краткий ответ"))],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=7),
    )
    provider = DeepSeekProvider(client=make_client(response), model="test-model")

    result = provider.generate(
        [Message(role=MessageRole.USER, content="Сообщение")]
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
        [Message(role=MessageRole.USER, content="Сообщение")]
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
            [Message(role=MessageRole.USER, content="Сообщение")]
        )


def test_generate_converts_connection_error() -> None:
    client = make_client(response=None)
    client.chat.completions.create.side_effect = APIConnectionError(
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    )
    provider = DeepSeekProvider(client=client, model="test-model")

    with pytest.raises(LLMUnavailableError):
        provider.generate(
            [Message(role=MessageRole.USER, content="Сообщение")]
        )
