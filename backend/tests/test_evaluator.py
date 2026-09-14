from uuid import UUID

from app.evals.evaluator import (
    ObservedLibraryEntry,
    ObservedToolCall,
    ScenarioObservation,
    evaluate_scenario,
)
from app.evals.models import EvalScenario
from app.llm.models import ModelResponse
from app.models import AgentRunStatus, ReadingStatus

RUN_ID = UUID("20000000-0000-0000-0000-000000000001")


def scenario(**overrides: object) -> EvalScenario:
    payload: dict[str, object] = {
        "id": "test-scenario",
        "input": "Добавь Дюну",
        "expected_tools": ["search_books", "add_book"],
        "optional_tools": ["get_user_library"],
        "forbidden_tools": ["remove_book"],
        "argument_invariants": [
            {"tool": "add_book", "contains": {"status": "want_to_read"}}
        ],
        "final_state": {
            "run_status": "completed",
            "library_contains": [
                {"title": "Дюна", "status": "want_to_read"}
            ],
            "answer_contains": ["Дюна"],
        },
        "max_steps": 4,
        "fake_responses": [ModelResponse(text="готово")],
    }
    payload.update(overrides)
    return EvalScenario.model_validate(payload)


def observation(**overrides: object) -> ScenarioObservation:
    payload: dict[str, object] = {
        "run_id": RUN_ID,
        "run_status": AgentRunStatus.COMPLETED,
        "final_answer": "Добавлена книга Дюна",
        "tool_calls": [
            ObservedToolCall(name="search_books", arguments={"query": "Дюна"}),
            ObservedToolCall(
                name="add_book",
                arguments={"status": "want_to_read"},
            ),
        ],
        "library": [
            ObservedLibraryEntry(
                title="Дюна",
                status=ReadingStatus.WANT_TO_READ,
            )
        ],
        "step_count": 3,
        "duration_ms": 20,
    }
    payload.update(overrides)
    return ScenarioObservation.model_validate(payload)


def test_evaluator_accepts_expected_tools_arguments_and_final_state() -> None:
    result = evaluate_scenario(scenario(), observation())

    assert result.success is True
    assert result.failures == []
    assert result.tool_precision == 1
    assert result.tool_recall == 1


def test_evaluator_counts_missing_unexpected_and_forbidden_calls() -> None:
    result = evaluate_scenario(
        scenario(),
        observation(
            tool_calls=[
                ObservedToolCall(
                    name="remove_book",
                    arguments={},
                    error_code="invalid_arguments",
                )
            ]
        ),
    )

    assert result.success is False
    assert result.tool_precision == 0
    assert result.tool_recall == 0
    assert result.forbidden_calls == 1
    assert result.invalid_argument_calls == 1
    assert "forbidden_tool_called" in result.failures


def test_beautiful_answer_cannot_hide_wrong_database_state() -> None:
    result = evaluate_scenario(
        scenario(),
        observation(final_answer="Успешно добавлена книга Дюна!", library=[]),
    )

    assert result.success is False
    assert result.failures == ["library_missing:Дюна:want_to_read"]


def test_step_limit_is_not_partial_success() -> None:
    result = evaluate_scenario(
        scenario(max_steps=2),
        observation(step_count=3),
    )

    assert result.success is False
    assert "max_steps_exceeded" in result.failures


def test_expected_duplicate_tool_calls_use_multiset_recall() -> None:
    duplicate_scenario = scenario(
        expected_tools=["search_books", "search_books"],
        argument_invariants=[],
        final_state={"run_status": "completed"},
    )

    result = evaluate_scenario(
        duplicate_scenario,
        observation(
            tool_calls=[
                ObservedToolCall(name="search_books", arguments={})
            ],
            library=[],
            final_answer="",
        ),
    )

    assert result.tool_recall == 0.5
    assert result.success is False
