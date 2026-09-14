from pathlib import Path

import pytest

from app.evals.baseline import (
    assert_matches_baseline,
    load_baseline,
    main,
)
from app.evals.models import load_dataset
from app.evals.runner import run_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET = PROJECT_ROOT / "evals" / "datasets" / "book_agent_v1.json"
BASELINE = PROJECT_ROOT / "evals" / "baselines" / "book_agent_v1.json"


def test_frozen_baseline_matches_scripted_eval(capsys) -> None:
    assert main([]) == 0
    assert '"status": "matched"' in capsys.readouterr().out


def test_baseline_detects_metric_regression() -> None:
    report = run_dataset(load_dataset(DATASET))
    regressed = report.model_copy(
        update={
            "metrics": report.metrics.model_copy(
                update={"successful_scenarios": 20, "task_success_rate": 20 / 21}
            )
        }
    )

    with pytest.raises(ValueError, match="eval baseline mismatch"):
        assert_matches_baseline(regressed, DATASET, load_baseline(BASELINE))
