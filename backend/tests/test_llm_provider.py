import pytest

from app.llm.fake import FakeLLMProvider
from app.llm.models import Message, MessageRole, ModelResponse
from app.llm.provider import LLMProvider
from app.tools.books import SEARCH_BOOKS_TOOL


def test_fake_returns_prepared_response() -> None:
    expected = ModelResponse(text="Первый ответ")
    provider: LLMProvider = FakeLLMProvider([expected])

    response = provider.generate(
        [Message(role=MessageRole.USER, content="Первый запрос")],
        tools=(),
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
        [Message(role=MessageRole.USER, content="Первый запрос")],
        tools=(),
    )
    second = provider.generate(
        [Message(role=MessageRole.USER, content="Второй запрос")],
        tools=(),
    )

    assert first.text == "Первый ответ"
    assert second.text == "Второй ответ"


def test_fake_records_a_copy_of_messages() -> None:
    provider = FakeLLMProvider([ModelResponse(text="Ответ")])
    messages = [Message(role=MessageRole.USER, content="Исходный запрос")]

    provider.generate(messages, tools=(SEARCH_BOOKS_TOOL,))
    messages.append(
        Message(role=MessageRole.ASSISTANT, content="Позднее изменение")
    )

    assert provider.calls == [
        [Message(role=MessageRole.USER, content="Исходный запрос")]
    ]
    assert provider.tools_by_call == [(SEARCH_BOOKS_TOOL,)]


def test_fake_raises_when_responses_are_exhausted() -> None:
    provider = FakeLLMProvider([])

    with pytest.raises(RuntimeError, match="No fake responses remaining"):
        provider.generate(
            [Message(role=MessageRole.USER, content="Запрос")],
            tools=(),
        )
