from app.llm.models import Message, MessageRole, ModelResponse
from app.llm.provider import LLMProvider

BOOK_ASSISTANT_SYSTEM_PROMPT = "Ты помощник по книгам. Отвечай кратко и точно."


class ChatService:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def reply(self, user_message: str) -> ModelResponse:
        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=BOOK_ASSISTANT_SYSTEM_PROMPT,
            ),
            Message(role=MessageRole.USER, content=user_message),
        ]
        return self.provider.generate(messages, tools=())
