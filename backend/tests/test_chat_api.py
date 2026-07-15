from fastapi.testclient import TestClient

from app.dependencies import get_llm_provider
from app.llm.fake import FakeLLMProvider
from app.llm.models import ModelResponse, TokenUsage
from app.main import app


def test_chat_returns_normalized_provider_response(client: TestClient) -> None:
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="Дюна — научно-фантастический роман.",
                response_id="fake-response-1",
                usage=TokenUsage(input_tokens=10, output_tokens=20),
            )
        ]
    )
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.post(
        "/api/chat",
        json={"message": "Кратко расскажи о Дюне"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "text": "Дюна — научно-фантастический роман.",
        "response_id": "fake-response-1",
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }
    assert len(provider.calls) == 1


def test_chat_rejects_empty_message_before_calling_provider(
    client: TestClient,
) -> None:
    provider = FakeLLMProvider([ModelResponse(text="Ответ")])
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.post("/api/chat", json={"message": ""})

    assert response.status_code == 422
    assert provider.calls == []
