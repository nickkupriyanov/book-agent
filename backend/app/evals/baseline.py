import argparse
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.evals.models import load_dataset
from app.evals.runner import EvalMetrics, EvalReport, run_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = PROJECT_ROOT / "evals" / "datasets" / "book_agent_v1.json"
DEFAULT_BASELINE = PROJECT_ROOT / "evals" / "baselines" / "book_agent_v1.json"


class StableMetrics(BaseModel):
    scenario_count: int
    successful_scenarios: int
    task_success_rate: float
    mean_tool_precision: float
    mean_tool_recall: float
    forbidden_calls: int
    invalid_argument_calls: int
    total_steps: int
    input_tokens: int | None
    output_tokens: int | None

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_metrics(cls, metrics: EvalMetrics) -> "StableMetrics":
        return cls.model_validate(
            metrics.model_dump(include=set(cls.model_fields))
        )


class EvalBaseline(BaseModel):
    dataset_version: str
    dataset_sha256: str
    prompt_version: str
    provider: str
    model: str
    metrics: StableMetrics

    model_config = ConfigDict(extra="forbid")


def dataset_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def baseline_from_report(report: EvalReport, dataset_path: Path) -> EvalBaseline:
    return EvalBaseline(
        dataset_version=report.dataset_version,
        dataset_sha256=dataset_sha256(dataset_path),
        prompt_version=report.prompt_version,
        provider=report.provider,
        model=report.model,
        metrics=StableMetrics.from_metrics(report.metrics),
    )


def load_baseline(path: Path) -> EvalBaseline:
    return EvalBaseline.model_validate_json(path.read_text(encoding="utf-8"))


def assert_matches_baseline(
    report: EvalReport,
    dataset_path: Path,
    expected: EvalBaseline,
) -> None:
    actual = baseline_from_report(report, dataset_path)
    if actual != expected:
        raise ValueError(
            "eval baseline mismatch:\n"
            f"expected={expected.model_dump_json()}\n"
            f"actual={actual.model_dump_json()}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the frozen agent baseline")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args(argv)

    report = run_dataset(load_dataset(args.dataset))
    try:
        assert_matches_baseline(
            report,
            args.dataset,
            load_baseline(args.baseline),
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    print(
        json.dumps(
            {
                "status": "matched",
                "dataset_version": report.dataset_version,
                "scenarios": report.metrics.scenario_count,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
