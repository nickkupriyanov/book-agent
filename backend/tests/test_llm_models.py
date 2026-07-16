import pytest
from pydantic import ValidationError

from app.llm.models import Message, MessageRole, ModelResponse, TokenUsage


def test_message_accepts_known_role() -> None:
    message = Message.model_validate(
        {"role": "user", "content": "Расскажи о Дюне"}
    )

    assert message.role is MessageRole.USER
    assert message.content == "Расскажи о Дюне"


def test_message_rejects_unknown_role() -> None:
    with pytest.raises(ValidationError):
        Message.model_validate(
            {"role": "admin", "content": "Расскажи о Дюне"}
        )


def test_token_usage_rejects_negative_values() -> None:
    with pytest.raises(ValidationError):
        TokenUsage(input_tokens=-1, output_tokens=10)


def test_model_response_allows_missing_metadata() -> None:
    response = ModelResponse(text="Дюна — научно-фантастический роман.")

    assert response.response_id is None
    assert response.usage is None


def test_model_response_contains_token_usage() -> None:
    response = ModelResponse(
        text="Дюна — научно-фантастический роман.",
        response_id="response-1",
        usage=TokenUsage(input_tokens=10, output_tokens=20),
    )

    assert response.response_id == "response-1"
    assert response.usage == TokenUsage(input_tokens=10, output_tokens=20)
