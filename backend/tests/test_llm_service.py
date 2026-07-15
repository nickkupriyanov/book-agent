from app.llm.fake import FakeLLMProvider
from app.llm.models import Message, ModelResponse
from app.llm.service import ChatService


def test_chat_service_returns_provider_response() -> None:
    expected = ModelResponse(text="Дюна — научно-фантастический роман.")
    provider = FakeLLMProvider([expected])
    service = ChatService(provider)

    response = service.reply("Кратко расскажи о Дюне")

    assert response == expected


def test_chat_service_sends_system_and_user_messages_once() -> None:
    provider = FakeLLMProvider([ModelResponse(text="Ответ")])
    service = ChatService(provider)

    service.reply("Кратко расскажи о Дюне")

    assert provider.calls == [
        [
            Message(
                role="system",
                content="Ты помощник по книгам. Отвечай кратко и точно.",
            ),
            Message(role="user", content="Кратко расскажи о Дюне"),
        ]
    ]
