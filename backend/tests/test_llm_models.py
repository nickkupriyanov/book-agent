import pytest
from pydantic import ValidationError

from app.llm.models import Message, MessageRole, ModelResponse, TokenUsage
from app.tools.models import ToolCall


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


def test_assistant_message_accepts_tool_calls() -> None:
    call = ToolCall(
        id="call-1",
        name="search_books",
        arguments={"query": "Дюна"},
    )

    message = Message(
        role=MessageRole.ASSISTANT,
        content="",
        tool_calls=[call],
    )

    assert message.tool_calls == [call]


def test_tool_message_requires_call_reference() -> None:
    message = Message(
        role=MessageRole.TOOL,
        content='{"books": []}',
        tool_call_id="call-1",
        tool_name="search_books",
    )

    assert message.tool_call_id == "call-1"
    assert message.tool_name == "search_books"


@pytest.mark.parametrize(
    "message",
    [
        {
            "role": "user",
            "content": "Запрос",
            "tool_calls": [
                {
                    "id": "call-1",
                    "name": "search_books",
                    "arguments": {"query": "Дюна"},
                }
            ],
        },
        {"role": "tool", "content": "{}"},
        {
            "role": "assistant",
            "content": "Ответ",
            "tool_call_id": "call-1",
            "tool_name": "search_books",
        },
    ],
)
def test_message_rejects_tool_fields_for_wrong_role(
    message: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        Message.model_validate(message)


def test_token_usage_rejects_negative_values() -> None:
    with pytest.raises(ValidationError):
        TokenUsage(input_tokens=-1, output_tokens=10)


def test_model_response_allows_missing_metadata() -> None:
    response = ModelResponse(text="Дюна — научно-фантастический роман.")

    assert response.response_id is None
    assert response.usage is None
    assert response.tool_calls == []


def test_model_response_contains_normalized_tool_calls() -> None:
    call = ToolCall(
        id="call-1",
        name="search_books",
        arguments={"query": "Дюна"},
    )

    response = ModelResponse(text="", tool_calls=[call])

    assert response.tool_calls == [call]


def test_model_response_contains_token_usage() -> None:
    response = ModelResponse(
        text="Дюна — научно-фантастический роман.",
        response_id="response-1",
        usage=TokenUsage(input_tokens=10, output_tokens=20),
    )

    assert response.response_id == "response-1"
    assert response.usage == TokenUsage(input_tokens=10, output_tokens=20)
