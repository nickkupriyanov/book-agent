import json
from pathlib import Path

from app.config import get_settings
from app.evals.cli import main
from app.evals.compare import compare_reports
from app.evals.runner import EvalReport

DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "datasets"
    / "book_agent_v1.json"
)


def test_fake_cli_writes_complete_safe_report(
    tmp_path: Path,
    capsys,
) -> None:
    output = tmp_path / "report.json"

    exit_code = main(["--dataset", str(DATASET_PATH), "--output", str(output)])

    report = EvalReport.model_validate_json(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert report.provider == "fake"
    assert report.model == "scripted"
    assert report.metrics.task_success_rate == 1
    assert all(result.safe_trace is not None for result in report.scenarios)
    assert "private" not in output.read_text(encoding="utf-8").casefold()
    assert json.loads(capsys.readouterr().out)["dataset_version"] == (
        report.dataset_version
    )


def test_live_cli_without_key_fails_before_any_scenario(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    get_settings.cache_clear()
    try:
        exit_code = main(
            ["--dataset", str(DATASET_PATH), "--provider", "deepseek"]
        )
    finally:
        get_settings.cache_clear()

    assert exit_code == 2
    assert "not configured" in capsys.readouterr().err


def test_comparison_reports_metric_deltas(tmp_path: Path, capsys) -> None:
    output = tmp_path / "report.json"
    assert main(["--dataset", str(DATASET_PATH), "--output", str(output)]) == 0
    capsys.readouterr()
    baseline = EvalReport.model_validate_json(output.read_text(encoding="utf-8"))
    candidate = baseline.model_copy(
        update={
            "provider": "candidate",
            "metrics": baseline.metrics.model_copy(
                update={"task_success_rate": 0.5, "successful_scenarios": 10}
            ),
        }
    )

    comparison = compare_reports(baseline, candidate)

    assert comparison.baseline.startswith("fake/scripted")
    assert comparison.candidate.startswith("candidate/scripted")
    assert comparison.deltas.task_success_rate == -0.5


def test_comparison_rejects_different_dataset_versions(tmp_path: Path, capsys) -> None:
    output = tmp_path / "report.json"
    assert main(["--dataset", str(DATASET_PATH), "--output", str(output)]) == 0
    capsys.readouterr()
    baseline = EvalReport.model_validate_json(output.read_text(encoding="utf-8"))
    candidate = baseline.model_copy(update={"dataset_version": "other"})

    try:
        compare_reports(baseline, candidate)
    except ValueError as exc:
        assert str(exc) == "reports must use the same dataset version"
    else:
        raise AssertionError("comparison should reject a different dataset")
