from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evals.models import EvalDataset, load_dataset

DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "datasets"
    / "book_agent_v1.json"
)


def test_versioned_dataset_contains_twenty_valid_scenarios() -> None:
    dataset = load_dataset(DATASET_PATH)

    assert dataset.version == "book-agent-evals-v1"
    assert dataset.prompt_version == "book-agent-system-v1"
    assert len(dataset.scenarios) >= 20
    assert len({scenario.id for scenario in dataset.scenarios}) == len(
        dataset.scenarios
    )
    assert all(scenario.final_state.run_status for scenario in dataset.scenarios)


def test_dataset_rejects_duplicate_ids() -> None:
    dataset = load_dataset(DATASET_PATH)
    payload = dataset.model_dump(mode="json")
    payload["scenarios"][1]["id"] = payload["scenarios"][0]["id"]

    with pytest.raises(ValidationError, match="scenario IDs must be unique"):
        EvalDataset.model_validate(payload)


def test_scenario_rejects_overlapping_tool_groups() -> None:
    dataset = load_dataset(DATASET_PATH)
    payload = dataset.model_dump(mode="json")
    payload["scenarios"][0]["forbidden_tools"] = ["search_books"]

    with pytest.raises(ValidationError, match="must be disjoint"):
        EvalDataset.model_validate(payload)


def test_invariant_must_reference_allowed_tool() -> None:
    dataset = load_dataset(DATASET_PATH)
    payload = dataset.model_dump(mode="json")
    payload["scenarios"][0]["argument_invariants"] = [
        {"tool": "execute_sql", "contains": {"query": "DROP TABLE books"}}
    ]

    with pytest.raises(ValidationError, match="expected or optional tool"):
        EvalDataset.model_validate(payload)
