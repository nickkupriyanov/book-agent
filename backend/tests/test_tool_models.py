import pytest
from pydantic import ValidationError

from app.tools.models import ToolCall, ToolError, ToolErrorCode, ToolResult


def test_tool_call_rejects_empty_and_extra_fields() -> None:
    invalid_calls = (
        {"id": "", "name": "search_books", "arguments": {}},
        {"id": "call-1", "name": "", "arguments": {}},
        {
            "id": "call-1",
            "name": "search_books",
            "arguments": {},
            "unexpected": True,
        },
    )

    for invalid_call in invalid_calls:
        with pytest.raises(ValidationError):
            ToolCall.model_validate(invalid_call)


def test_tool_result_rejects_output_and_error_together() -> None:
    with pytest.raises(ValidationError, match="exactly one of output or error"):
        ToolResult(
            tool_call_id="call-1",
            tool_name="search_books",
            output={"books": []},
            error=ToolError(
                code=ToolErrorCode.INVALID_RESULT,
                message="Tool returned an invalid result",
            ),
        )


def test_tool_result_requires_output_or_error() -> None:
    with pytest.raises(ValidationError, match="exactly one of output or error"):
        ToolResult(tool_call_id="call-1", tool_name="search_books")
