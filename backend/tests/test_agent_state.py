import pytest
from pydantic import ValidationError

from app.agent.state import AgentWorkingState, CompletedAction


def test_working_state_accepts_strict_valid_state() -> None:
    state = AgentWorkingState(
        goal="Найди и добавь Дюну",
        completed_actions=[
            CompletedAction(
                step_number=1,
                tool_call_id="search-1",
                tool_name="search_books",
            )
        ],
        initial_step_budget=5,
        remaining_step_budget=4,
    )

    assert state.goal == "Найди и добавь Дюну"
    assert state.completed_actions[0].tool_name == "search_books"


def test_working_state_rejects_invalid_budget_and_extra_fields() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        AgentWorkingState(
            goal="Найди Дюну",
            initial_step_budget=2,
            remaining_step_budget=3,
        )

    with pytest.raises(ValidationError):
        AgentWorkingState.model_validate(
            {
                "goal": "Найди Дюну",
                "completed_actions": [],
                "initial_step_budget": 2,
                "remaining_step_budget": 2,
                "arbitrary": "data",
            }
        )


def test_completed_action_rejects_missing_identity() -> None:
    with pytest.raises(ValidationError):
        CompletedAction(
            step_number=1,
            tool_call_id="",
            tool_name="search_books",
        )
