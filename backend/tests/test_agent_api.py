import json
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
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
    assert payload["steps"][0]["catalog_searches"] == [
        {"source": "local", "degraded": False, "cached": False}
    ]
    assert payload["steps"][1]["catalog_searches"] == []
    assert payload["steps"][2]["catalog_searches"] == []

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


def test_remove_book_run_returns_safe_pending_action_and_survives_new_session(
    client: TestClient,
    session: Session,
) -> None:
    add_response = client.post(
        "/api/library",
        json={"book_id": DUNE_ID, "status": "reading"},
    )
    assert add_response.status_code == 201
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="remove-1",
                        name="remove_book",
                        arguments={"book_id": DUNE_ID},
                    )
                ],
            )
        ]
    )
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.post(
        "/api/agent/runs",
        json={"message": "Удали Дюну из моей библиотеки"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "waiting_for_approval"
    assert payload["final_answer"] is None
    assert set(payload["pending_action"]) == {
        "id",
        "summary",
        "status",
        "expires_at",
    }
    assert payload["pending_action"]["status"] == "pending"
    assert payload["pending_action"]["summary"] == (
        "Удалить «Дюна» (Фрэнк Герберт) из вашей библиотеки."
    )
    assert "arguments" not in payload["pending_action"]
    assert "idempotency_key" not in payload["pending_action"]
    assert len(client.get("/api/library").json()) == 1

    bind = session.get_bind()

    def override_get_db_with_new_session():
        with Session(bind) as restarted_session:
            yield restarted_session

    app.dependency_overrides[get_db] = override_get_db_with_new_session
    with TestClient(app) as restarted_client:
        restored_response = restarted_client.get(
            f"/api/agent/runs/{payload['id']}"
        )

    assert restored_response.status_code == 200
    assert restored_response.json()["pending_action"] == payload["pending_action"]


def test_approve_executes_once_resumes_run_and_rejects_replacement_arguments(
    client: TestClient,
) -> None:
    assert client.post(
        "/api/library",
        json={"book_id": DUNE_ID, "status": "reading"},
    ).status_code == 201
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="remove-1",
                        name="remove_book",
                        arguments={"book_id": DUNE_ID},
                    )
                ],
            ),
            ModelResponse(text="Удалил «Дюну» из вашей библиотеки."),
        ]
    )
    app.dependency_overrides[get_llm_provider] = lambda: provider
    waiting = client.post(
        "/api/agent/runs",
        json={"message": "Удали Дюну"},
    ).json()
    approve_url = (
        f"/api/agent/runs/{waiting['id']}/actions/"
        f"{waiting['pending_action']['id']}/approve"
    )

    replacement = client.post(
        approve_url,
        json={"arguments": {"book_id": "10000000-0000-0000-0000-000000000002"}},
    )

    assert replacement.status_code == 422
    assert len(client.get("/api/library").json()) == 1

    approved = client.post(approve_url, json={})

    assert approved.status_code == 200
    payload = approved.json()
    assert payload["replayed"] is False
    assert payload["action"]["status"] == "approved"
    assert payload["action"]["result"]["output"] == {
        "book_id": DUNE_ID,
        "title": "Дюна",
        "author": "Фрэнк Герберт",
        "status": "reading",
    }
    assert payload["run"]["status"] == "completed"
    assert payload["run"]["final_answer"] == (
        "Удалил «Дюну» из вашей библиотеки."
    )
    assert payload["run"]["pending_action"] is None
    assert payload["run"]["steps"][0]["tool_results"] == [
        payload["action"]["result"]
    ]
    assert len(payload["run"]["steps"]) == 2
    assert client.get("/api/library").json() == []
    assert len(provider.calls) == 2

    replay = client.post(approve_url, json={})

    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["action"]["result"] == payload["action"]["result"]
    assert replay.json()["run"]["status"] == "completed"
    assert len(provider.calls) == 2


def test_provider_failure_after_approve_keeps_effect_and_replay_is_safe(
    client: TestClient,
    session: Session,
) -> None:
    assert client.post(
        "/api/library",
        json={"book_id": DUNE_ID, "status": "reading"},
    ).status_code == 201
    provider = Mock()
    provider.generate.side_effect = [
        ModelResponse(
            text="",
            tool_calls=[
                ToolCall(
                    id="remove-1",
                    name="remove_book",
                    arguments={"book_id": DUNE_ID},
                )
            ],
        ),
        LLMTimeoutError("provider failed after commit"),
    ]
    app.dependency_overrides[get_llm_provider] = lambda: provider
    waiting = client.post(
        "/api/agent/runs",
        json={"message": "Удали Дюну"},
    ).json()
    approve_url = (
        f"/api/agent/runs/{waiting['id']}/actions/"
        f"{waiting['pending_action']['id']}/approve"
    )

    failed = client.post(approve_url, json={})

    assert failed.status_code == 504
    assert client.get("/api/library").json() == []
    session.expire_all()
    run = session.scalar(select(AgentRun))
    assert run is not None
    assert run.status is AgentRunStatus.FAILED
    assert run.pending_actions[0].status.value == "approved"
    assert run.pending_actions[0].result is not None
    assert provider.generate.call_count == 2

    replay = client.post(approve_url, json={})

    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["run"]["status"] == "failed"
    assert client.get("/api/library").json() == []
    assert provider.generate.call_count == 2


def test_reject_keeps_book_resumes_protocol_and_replay_is_stable(
    client: TestClient,
) -> None:
    assert client.post(
        "/api/library",
        json={"book_id": DUNE_ID, "status": "reading"},
    ).status_code == 201
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="remove-1",
                        name="remove_book",
                        arguments={"book_id": DUNE_ID},
                    )
                ],
            ),
            ModelResponse(text="Хорошо, книга осталась в библиотеке."),
        ]
    )
    app.dependency_overrides[get_llm_provider] = lambda: provider
    waiting = client.post(
        "/api/agent/runs",
        json={"message": "Удали Дюну"},
    ).json()
    reject_url = (
        f"/api/agent/runs/{waiting['id']}/actions/"
        f"{waiting['pending_action']['id']}/reject"
    )

    replacement = client.post(reject_url, json={"reason": "delete another book"})

    assert replacement.status_code == 422
    assert len(provider.calls) == 1
    assert len(client.get("/api/library").json()) == 1

    rejected = client.post(reject_url, json={})

    assert rejected.status_code == 200
    payload = rejected.json()
    assert payload["replayed"] is False
    assert payload["action"]["status"] == "rejected"
    assert payload["action"]["result"]["error"] == {
        "code": "user_rejected",
        "message": "User rejected the proposed action",
    }
    assert payload["run"]["status"] == "completed"
    assert payload["run"]["final_answer"] == (
        "Хорошо, книга осталась в библиотеке."
    )
    assert len(client.get("/api/library").json()) == 1
    assert len(provider.calls) == 2
    resumed_messages = provider.calls[1]
    assert [message.role.value for message in resumed_messages[-2:]] == [
        "assistant",
        "tool",
    ]
    assert resumed_messages[-2].tool_calls[0].id == "remove-1"
    assert resumed_messages[-1].tool_call_id == "remove-1"
    assert json.loads(resumed_messages[-1].content)["error"]["code"] == (
        "user_rejected"
    )
    assert payload["run"]["steps"][0]["tool_results"] == [
        payload["action"]["result"]
    ]
    assert payload["run"]["working_state"]["completed_actions"] == []

    replay = client.post(reject_url, json={})

    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["action"]["result"] == payload["action"]["result"]
    assert replay.json()["run"]["status"] == "completed"
    assert len(provider.calls) == 2
    assert len(client.get("/api/library").json()) == 1


def test_reject_with_exhausted_budget_does_not_call_provider_again(
    client: TestClient,
) -> None:
    assert client.post(
        "/api/library",
        json={"book_id": DUNE_ID, "status": "reading"},
    ).status_code == 201
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="remove-1",
                        name="remove_book",
                        arguments={"book_id": DUNE_ID},
                    )
                ],
            )
        ]
    )
    app.dependency_overrides[get_llm_provider] = lambda: provider
    original_settings_override = app.dependency_overrides.get(get_settings)
    app.dependency_overrides[get_settings] = lambda: Settings(agent_max_steps=1)
    try:
        waiting = client.post(
            "/api/agent/runs",
            json={"message": "Удали Дюну"},
        ).json()
        reject_url = (
            f"/api/agent/runs/{waiting['id']}/actions/"
            f"{waiting['pending_action']['id']}/reject"
        )

        rejected = client.post(reject_url, json={})
    finally:
        if original_settings_override is None:
            app.dependency_overrides.pop(get_settings, None)
        else:
            app.dependency_overrides[get_settings] = original_settings_override

    assert rejected.status_code == 200
    payload = rejected.json()
    assert payload["action"]["status"] == "rejected"
    assert payload["run"]["status"] == "step_limit_exceeded"
    assert payload["run"]["stop_reason"] == "max_steps"
    assert payload["run"]["working_state"]["remaining_step_budget"] == 0
    assert len(provider.calls) == 1
    assert len(client.get("/api/library").json()) == 1
