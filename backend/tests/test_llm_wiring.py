from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch

from app.config import Settings, get_settings
from app.dependencies import get_llm_provider
from app.llm.models import Message, MessageRole
from app.main import app


def test_settings_read_deepseek_configuration(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek.example")
    monkeypatch.setenv("DEEPSEEK_MODEL", "test-model")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("AGENT_MAX_STEPS", "7")

    settings = Settings()

    assert isinstance(settings.deepseek_api_key, SecretStr)
    assert settings.deepseek_api_key.get_secret_value() == "test-secret"
    assert settings.deepseek_base_url == "https://deepseek.example"
    assert settings.deepseek_model == "test-model"
    assert settings.deepseek_timeout_seconds == 12.5
    assert settings.agent_max_steps == 7


def test_get_llm_provider_builds_configured_deepseek_client() -> None:
    settings = Settings(
        deepseek_api_key=SecretStr("test-secret"),
        deepseek_base_url="https://deepseek.example",
        deepseek_model="test-model",
        deepseek_timeout_seconds=12.5,
    )
    sdk_client = Mock()
    sdk_client.chat.completions.create.return_value = SimpleNamespace(
        id="response-1",
        choices=[SimpleNamespace(message=SimpleNamespace(content="Ответ"))],
        usage=None,
    )

    with patch("app.dependencies.OpenAI", return_value=sdk_client) as openai_class:
        provider = get_llm_provider(settings)
        provider.generate(
            [Message(role=MessageRole.USER, content="Вопрос")],
            tools=(),
        )

    openai_class.assert_called_once_with(
        api_key="test-secret",
        base_url="https://deepseek.example",
        timeout=12.5,
        max_retries=0,
    )
    sdk_client.chat.completions.create.assert_called_once_with(
        model="test-model",
        messages=[{"role": "user", "content": "Вопрос"}],
    )


def test_chat_returns_503_when_deepseek_api_key_is_missing(
    client: TestClient,
) -> None:
    settings = Settings(deepseek_api_key=None)
    app.dependency_overrides[get_settings] = lambda: settings

    response = client.post("/api/chat", json={"message": "Расскажи о Дюне"})

    assert response.status_code == 503
    assert response.json() == {"detail": "LLM provider is not configured"}
