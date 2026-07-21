from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.repository import AgentRunRepository
from app.models import AgentRunStatus

USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_agent_trace_is_restored_in_step_order(session: Session) -> None:
    repository = AgentRunRepository(session)
    run = repository.create_run(USER_ID, "Найди Дюну")

    repository.add_step(
        run_id=run.id,
        step_number=2,
        messages=[{"role": "tool", "content": '{"books": []}'}],
        response={"text": "Дюна найдена", "tool_calls": []},
        tool_results=[],
        error=None,
        duration_ms=18,
    )
    repository.add_step(
        run_id=run.id,
        step_number=1,
        messages=[{"role": "user", "content": "Найди Дюну"}],
        response={
            "text": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "name": "search_books",
                    "arguments": {"query": "Дюна"},
                }
            ],
        },
        tool_results=[
            {
                "tool_call_id": "call-1",
                "tool_name": "search_books",
                "output": {"books": []},
            }
        ],
        error=None,
        duration_ms=25,
    )
    run.status = AgentRunStatus.COMPLETED
    run.final_answer = "Дюна найдена"
    run.stop_reason = "final_response"
    repository.save_run(run)

    with Session(session.get_bind()) as another_session:
        restored = AgentRunRepository(another_session).get_run(run.id)

        assert restored is not None
        assert restored.user_id == USER_ID
        assert restored.user_message == "Найди Дюну"
        assert restored.status is AgentRunStatus.COMPLETED
        assert restored.final_answer == "Дюна найдена"
        assert restored.stop_reason == "final_response"
        assert restored.error is None
        assert [step.step_number for step in restored.steps] == [1, 2]
        assert restored.steps[0].response == {
            "text": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "name": "search_books",
                    "arguments": {"query": "Дюна"},
                }
            ],
        }
        assert restored.steps[0].tool_results[0]["tool_call_id"] == "call-1"
        assert restored.steps[1].duration_ms == 18


def test_agent_steps_reject_duplicate_number_per_run(session: Session) -> None:
    repository = AgentRunRepository(session)
    run = repository.create_run(USER_ID, "Найди Дюну")
    step_data = {
        "run_id": run.id,
        "step_number": 1,
        "messages": [],
        "response": None,
        "tool_results": [],
        "error": "Provider failed",
        "duration_ms": 10,
    }
    repository.add_step(**step_data)

    with pytest.raises(IntegrityError):
        repository.add_step(**step_data)
