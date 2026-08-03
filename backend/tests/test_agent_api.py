from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_llm_provider
from app.llm.exceptions import LLMTimeoutError
from app.llm.fake import FakeLLMProvider
from app.llm.models import ModelResponse
from app.main import app
from app.models import AgentRun, AgentRunStatus
from app.tools.models import ToolCall

DUNE_ID = "10000000-0000-0000-0000-000000000001"


def test_create_agent_run_executes_tools_and_returns_trace(
    client: TestClient,
) -> None:
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="search-1",
                        name="search_books",
                        arguments={"query": "Дюна", "limit": 5},
                    )
                ],
            ),
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="add-1",
                        name="add_book",
                        arguments={
                            "book_id": DUNE_ID,
                            "status": "want_to_read",
                        },
                    )
                ],
            ),
            ModelResponse(text="Добавил «Дюну» в список на чтение."),
        ]
    )
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.post(
        "/api/agent/runs",
        json={"message": "Найди Дюну и добавь в список на чтение"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["user_message"] == "Найди Дюну и добавь в список на чтение"
    assert payload["working_state"] == {
        "goal": "Найди Дюну и добавь в список на чтение",
        "completed_actions": [
            {
                "step_number": 1,
                "tool_call_id": "search-1",
                "tool_name": "search_books",
            },
            {
                "step_number": 2,
                "tool_call_id": "add-1",
                "tool_name": "add_book",
            },
        ],
        "initial_step_budget": 5,
        "remaining_step_budget": 2,
    }
    assert payload["final_answer"] == "Добавил «Дюну» в список на чтение."
    assert payload["stop_reason"] == "final_response"
    assert payload["error"] is None
    assert [step["step_number"] for step in payload["steps"]] == [1, 2, 3]
    assert [
        step["response"]["tool_calls"][0]["name"]
        for step in payload["steps"]
        if step["response"]["tool_calls"]
    ] == ["search_books", "add_book"]
    assert payload["steps"][0]["tool_results"][0]["tool_call_id"] == "search-1"
    assert payload["steps"][1]["tool_results"][0]["tool_call_id"] == "add-1"

    library = client.get("/api/library").json()
    assert len(library) == 1
    assert library[0]["book"]["id"] == DUNE_ID
    assert library[0]["status"] == "want_to_read"
    assert len(provider.calls) == 3


def test_create_agent_run_rejects_empty_message_before_model_call(
    client: TestClient,
) -> None:
    provider = FakeLLMProvider([ModelResponse(text="Ответ")])
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.post("/api/agent/runs", json={"message": ""})

    assert response.status_code == 422
    assert provider.calls == []


def test_create_agent_run_preserves_provider_http_error_and_trace(
    client: TestClient,
    session: Session,
) -> None:
    provider = Mock()
    provider.generate.side_effect = LLMTimeoutError("internal SDK details")
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.post(
        "/api/agent/runs",
        json={"message": "Найди Дюну"},
    )

    assert response.status_code == 504
    assert response.json() == {"detail": "LLM provider timed out"}
    assert "internal SDK details" not in response.text
    run = session.scalar(select(AgentRun))
    assert run is not None
    assert run.status is AgentRunStatus.FAILED
    assert run.stop_reason == "provider_error"
    assert run.steps[0].error == "LLMTimeoutError"
