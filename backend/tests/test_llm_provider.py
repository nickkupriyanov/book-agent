import pytest

from app.llm.fake import FakeLLMProvider
from app.llm.models import Message, MessageRole, ModelResponse
from app.llm.provider import LLMProvider


def test_fake_returns_prepared_response() -> None:
    expected = ModelResponse(text="Первый ответ")
    provider: LLMProvider = FakeLLMProvider([expected])

    response = provider.generate(
        [Message(role=MessageRole.USER, content="Первый запрос")]
    )

    assert response == expected


def test_fake_returns_responses_in_order() -> None:
    provider = FakeLLMProvider(
        [
            ModelResponse(text="Первый ответ"),
            ModelResponse(text="Второй ответ"),
        ]
    )

    first = provider.generate(
        [Message(role=MessageRole.USER, content="Первый запрос")]
    )
    second = provider.generate(
        [Message(role=MessageRole.USER, content="Второй запрос")]
    )

    assert first.text == "Первый ответ"
    assert second.text == "Второй ответ"


def test_fake_records_a_copy_of_messages() -> None:
    provider = FakeLLMProvider([ModelResponse(text="Ответ")])
    messages = [Message(role=MessageRole.USER, content="Исходный запрос")]

    provider.generate(messages)
    messages.append(
        Message(role=MessageRole.ASSISTANT, content="Позднее изменение")
    )

    assert provider.calls == [
        [Message(role=MessageRole.USER, content="Исходный запрос")]
    ]


def test_fake_raises_when_responses_are_exhausted() -> None:
    provider = FakeLLMProvider([])

    with pytest.raises(RuntimeError, match="No fake responses remaining"):
        provider.generate([Message(role=MessageRole.USER, content="Запрос")])
