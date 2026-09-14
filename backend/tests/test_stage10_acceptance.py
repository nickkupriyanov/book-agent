from pathlib import Path

from app.agent.service import AGENT_PROMPT_VERSION
from app.evals.models import load_dataset
from app.evals.runner import run_dataset
from app.llm.models import ModelResponse

DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "datasets"
    / "book_agent_v1.json"
)


def test_full_baseline_has_zero_forbidden_calls_and_versioned_safe_traces() -> None:
    dataset = load_dataset(DATASET_PATH)

    report = run_dataset(dataset)

    assert dataset.prompt_version == AGENT_PROMPT_VERSION
    assert report.metrics.task_success_rate == 1
    assert report.metrics.forbidden_calls == 0
    assert report.metrics.invalid_argument_calls == 0
    assert all(
        result.safe_trace is not None
        and result.safe_trace.run_id == result.run_id
        and result.safe_trace.prompt_version == AGENT_PROMPT_VERSION
        for result in report.scenarios
    )


def test_regression_pretty_answer_without_database_change_has_failure_trace() -> None:
    dataset = load_dataset(DATASET_PATH)
    original = next(
        scenario
        for scenario in dataset.scenarios
        if scenario.id == "add-dune-want-to-read"
    )
    broken = original.model_copy(
        update={
            "fake_responses": [
                ModelResponse(text="Готово, я успешно добавил Дюну!")
            ]
        }
    )
    broken_dataset = dataset.model_copy(update={"scenarios": [broken]})

    report = run_dataset(broken_dataset)
    result = report.scenarios[0]

    assert report.metrics.task_success_rate == 0
    assert result.success is False
    assert "missing_expected_tools" in result.failures
    assert "library_missing:Дюна:want_to_read" in result.failures
    assert result.safe_trace is not None
    assert result.safe_trace.run_id == result.run_id
    assert result.safe_trace.status.value == "completed"
