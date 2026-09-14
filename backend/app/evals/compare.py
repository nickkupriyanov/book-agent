import argparse
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.evals.runner import EvalReport


class MetricDeltas(BaseModel):
    task_success_rate: float
    mean_tool_precision: float
    mean_tool_recall: float
    forbidden_calls: int
    invalid_argument_calls: int
    mean_steps: float

    model_config = ConfigDict(extra="forbid")


class EvalComparison(BaseModel):
    dataset_version: str
    baseline: str
    candidate: str
    deltas: MetricDeltas

    model_config = ConfigDict(extra="forbid")


def compare_reports(
    baseline: EvalReport,
    candidate: EvalReport,
) -> EvalComparison:
    if baseline.dataset_version != candidate.dataset_version:
        raise ValueError("reports must use the same dataset version")
    baseline_ids = [scenario.scenario_id for scenario in baseline.scenarios]
    candidate_ids = [scenario.scenario_id for scenario in candidate.scenarios]
    if baseline_ids != candidate_ids:
        raise ValueError("reports must contain the same scenarios in the same order")

    before = baseline.metrics
    after = candidate.metrics
    return EvalComparison(
        dataset_version=baseline.dataset_version,
        baseline=f"{baseline.provider}/{baseline.model}/{baseline.prompt_version}",
        candidate=f"{candidate.provider}/{candidate.model}/{candidate.prompt_version}",
        deltas=MetricDeltas(
            task_success_rate=after.task_success_rate - before.task_success_rate,
            mean_tool_precision=(
                after.mean_tool_precision - before.mean_tool_precision
            ),
            mean_tool_recall=after.mean_tool_recall - before.mean_tool_recall,
            forbidden_calls=after.forbidden_calls - before.forbidden_calls,
            invalid_argument_calls=(
                after.invalid_argument_calls - before.invalid_argument_calls
            ),
            mean_steps=after.mean_steps - before.mean_steps,
        ),
    )


def _load_report(path: Path) -> EvalReport:
    return EvalReport.model_validate_json(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two agent eval reports")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args(argv)
    comparison = compare_reports(
        _load_report(args.baseline),
        _load_report(args.candidate),
    )
    print(json.dumps(comparison.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
