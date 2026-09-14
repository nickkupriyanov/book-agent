from pathlib import Path

from app.evals.models import load_dataset
from app.evals.runner import run_dataset

DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "datasets"
    / "book_agent_v1.json"
)


def test_fake_runner_passes_full_dataset_without_network() -> None:
    report = run_dataset(load_dataset(DATASET_PATH))

    assert report.metrics.scenario_count >= 20
    assert report.metrics.successful_scenarios == report.metrics.scenario_count
    assert report.metrics.task_success_rate == 1
    assert report.metrics.mean_tool_precision == 1
    assert report.metrics.mean_tool_recall == 1
    assert report.metrics.forbidden_calls == 0
    assert report.metrics.invalid_argument_calls == 0
    assert report.metrics.total_steps > report.metrics.scenario_count
    assert {result.scenario_id for result in report.scenarios} == {
        scenario.id for scenario in load_dataset(DATASET_PATH).scenarios
    }


def test_fake_runner_produces_same_scores_on_repeat() -> None:
    dataset = load_dataset(DATASET_PATH)

    first = run_dataset(dataset)
    second = run_dataset(dataset)

    assert [result.success for result in first.scenarios] == [
        result.success for result in second.scenarios
    ]
    assert first.metrics.model_dump(exclude={"total_duration_ms"}) == (
        second.metrics.model_dump(exclude={"total_duration_ms"})
    )
