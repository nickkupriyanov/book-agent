from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.dependencies import get_llm_provider
from app.llm.fake import FakeLLMProvider
from app.llm.exceptions import LLMTimeoutError, LLMUnavailableError
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


def test_chat_returns_504_when_provider_times_out(client: TestClient) -> None:
    provider = Mock()
    provider.generate.side_effect = LLMTimeoutError("internal SDK details")
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.post("/api/chat", json={"message": "Расскажи о Дюне"})

    assert response.status_code == 504
    assert response.json() == {"detail": "LLM provider timed out"}
    assert "internal SDK details" not in response.text


def test_chat_returns_503_when_provider_is_unavailable(
    client: TestClient,
) -> None:
    provider = Mock()
    provider.generate.side_effect = LLMUnavailableError("internal SDK details")
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.post("/api/chat", json={"message": "Расскажи о Дюне"})

    assert response.status_code == 503
    assert response.json() == {"detail": "LLM provider is unavailable"}
    assert "internal SDK details" not in response.text
