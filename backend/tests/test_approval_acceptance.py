import json
from collections.abc import Generator, Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_llm_provider
from app.llm.fake import FakeLLMProvider
from app.llm.models import ModelResponse
from app.main import app
from app.tools.models import ToolCall

DUNE_ID = "10000000-0000-0000-0000-000000000001"


@contextmanager
def restarted_client(
    bind,
    provider: FakeLLMProvider,
) -> Iterator[TestClient]:
    def override_get_db() -> Generator[Session, None, None]:
        with Session(bind) as restarted_session:
            yield restarted_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider] = lambda: provider
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_approve_workflow_survives_restart_and_replay(session: Session) -> None:
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="remove-acceptance-1",
                        name="remove_book",
                        arguments={"book_id": DUNE_ID},
                    )
                ],
            ),
            ModelResponse(text="Операция завершена."),
        ]
    )
    bind = session.get_bind()

    with restarted_client(bind, provider) as first_app:
        assert first_app.post(
            "/api/library",
            json={"book_id": DUNE_ID, "status": "reading"},
        ).status_code == 201
        waiting = first_app.post(
            "/api/agent/runs",
            json={"message": "Удали Дюну"},
        ).json()

        assert waiting["status"] == "waiting_for_approval"
        assert waiting["pending_action"]["status"] == "pending"
        assert waiting["steps"][0]["response"]["tool_calls"][0] == {
            "id": "remove-acceptance-1",
            "name": "remove_book",
            "arguments": {"book_id": DUNE_ID},
        }
        assert waiting["steps"][0]["tool_results"] == []
        assert len(first_app.get("/api/library").json()) == 1

    approve_url = (
        f"/api/agent/runs/{waiting['id']}/actions/"
        f"{waiting['pending_action']['id']}/approve"
    )
    with restarted_client(bind, provider) as second_app:
        approved_response = second_app.post(approve_url, json={})

        assert approved_response.status_code == 200
        approved = approved_response.json()
        assert approved["replayed"] is False
        assert approved["action"]["status"] == "approved"
        assert approved["action"]["result"]["output"]["book_id"] == DUNE_ID
        assert approved["run"]["status"] == "completed"
        assert approved["run"]["stop_reason"] == "final_response"
        assert approved["run"]["pending_action"] is None
        assert approved["run"]["steps"][0]["tool_results"] == [
            approved["action"]["result"]
        ]
        assert approved["run"]["working_state"]["completed_actions"] == [
            {
                "step_number": 1,
                "tool_call_id": "remove-acceptance-1",
                "tool_name": "remove_book",
            }
        ]
        assert second_app.get("/api/library").json() == []

    resumed_messages = provider.calls[1]
    assert [message.role.value for message in resumed_messages[-2:]] == [
        "assistant",
        "tool",
    ]
    assert resumed_messages[-2].tool_calls[0].id == "remove-acceptance-1"
    assert resumed_messages[-1].tool_call_id == "remove-acceptance-1"
    assert json.loads(resumed_messages[-1].content) == approved["action"]["result"]

    with restarted_client(bind, provider) as third_app:
        replay_response = third_app.post(approve_url, json={})

        assert replay_response.status_code == 200
        replay = replay_response.json()
        assert replay["replayed"] is True
        assert replay["action"]["result"] == approved["action"]["result"]
        assert replay["run"]["status"] == "completed"
        assert third_app.get("/api/library").json() == []

    assert len(provider.calls) == 2


def test_reject_workflow_survives_restart_without_effect(session: Session) -> None:
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="remove-acceptance-2",
                        name="remove_book",
                        arguments={"book_id": DUNE_ID},
                    )
                ],
            ),
            ModelResponse(text="Операция отменена."),
        ]
    )
    bind = session.get_bind()

    with restarted_client(bind, provider) as first_app:
        assert first_app.post(
            "/api/library",
            json={"book_id": DUNE_ID, "status": "reading"},
        ).status_code == 201
        waiting = first_app.post(
            "/api/agent/runs",
            json={"message": "Удали Дюну"},
        ).json()

        assert waiting["status"] == "waiting_for_approval"
        assert waiting["steps"][0]["tool_results"] == []
        assert len(first_app.get("/api/library").json()) == 1

    reject_url = (
        f"/api/agent/runs/{waiting['id']}/actions/"
        f"{waiting['pending_action']['id']}/reject"
    )
    with restarted_client(bind, provider) as second_app:
        rejected_response = second_app.post(reject_url, json={})

        assert rejected_response.status_code == 200
        rejected = rejected_response.json()
        assert rejected["replayed"] is False
        assert rejected["action"]["status"] == "rejected"
        assert rejected["action"]["result"]["error"]["code"] == "user_rejected"
        assert rejected["run"]["status"] == "completed"
        assert rejected["run"]["pending_action"] is None
        assert rejected["run"]["steps"][0]["tool_results"] == [
            rejected["action"]["result"]
        ]
        assert rejected["run"]["working_state"]["completed_actions"] == []
        assert len(second_app.get("/api/library").json()) == 1

    resumed_messages = provider.calls[1]
    assert resumed_messages[-2].tool_calls[0].id == "remove-acceptance-2"
    assert resumed_messages[-1].tool_call_id == "remove-acceptance-2"
    assert json.loads(resumed_messages[-1].content)["error"]["code"] == (
        "user_rejected"
    )

    with restarted_client(bind, provider) as third_app:
        replay_response = third_app.post(reject_url, json={})

        assert replay_response.status_code == 200
        replay = replay_response.json()
        assert replay["replayed"] is True
        assert replay["action"]["result"] == rejected["action"]["result"]
        assert replay["run"]["status"] == "completed"
        assert len(third_app.get("/api/library").json()) == 1

    assert len(provider.calls) == 2
