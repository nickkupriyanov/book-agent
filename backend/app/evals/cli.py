import argparse
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.dependencies import get_llm_provider
from app.evals.models import load_dataset
from app.evals.runner import run_dataset
from app.llm.exceptions import LLMNotConfiguredError

DEFAULT_DATASET = (
    Path(__file__).resolve().parents[3]
    / "evals"
    / "datasets"
    / "book_agent_v1.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run book-agent evaluations")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--provider",
        choices=("fake", "deepseek"),
        default="fake",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    dataset = load_dataset(args.dataset)
    if args.provider == "fake":
        report = run_dataset(dataset)
    else:
        settings = get_settings()
        try:
            provider = get_llm_provider(settings)
        except LLMNotConfiguredError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        report = run_dataset(
            dataset,
            provider_factory=lambda _: provider,
            provider_name="deepseek",
            model_name=settings.deepseek_model,
        )

    serialized = json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )
    if args.output is not None:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report.metrics.task_success_rate == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
