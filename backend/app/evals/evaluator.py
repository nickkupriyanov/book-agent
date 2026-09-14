from collections import Counter
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.evals.models import EvalScenario
from app.models import AgentRunStatus, ReadingStatus


class ObservedToolCall(BaseModel):
    name: str
    arguments: dict[str, object]
    error_code: str | None = None

    model_config = ConfigDict(extra="forbid")


class ObservedLibraryEntry(BaseModel):
    title: str
    status: ReadingStatus

    model_config = ConfigDict(extra="forbid")


class ScenarioObservation(BaseModel):
    run_id: UUID
    run_status: AgentRunStatus
    final_answer: str | None
    tool_calls: list[ObservedToolCall]
    library: list[ObservedLibraryEntry]
    step_count: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")


class ScenarioEvaluation(BaseModel):
    scenario_id: str
    run_id: UUID
    success: bool
    failures: list[str]
    tool_precision: float = Field(ge=0, le=1)
    tool_recall: float = Field(ge=0, le=1)
    forbidden_calls: int = Field(ge=0)
    invalid_argument_calls: int = Field(ge=0)
    step_count: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")


def _multiset_recall(expected: list[str], observed: list[str]) -> float:
    if not expected:
        return 1.0
    expected_counts = Counter(expected)
    observed_counts = Counter(observed)
    matched = sum(
        min(count, observed_counts[name])
        for name, count in expected_counts.items()
    )
    return matched / len(expected)


def _tool_precision(
    expected: list[str],
    optional: list[str],
    observed: list[str],
) -> float:
    if not observed:
        return 1.0 if not expected else 0.0
    allowed = set(expected) | set(optional)
    return sum(name in allowed for name in observed) / len(observed)


def evaluate_scenario(
    scenario: EvalScenario,
    observation: ScenarioObservation,
) -> ScenarioEvaluation:
    failures: list[str] = []
    observed_names = [call.name for call in observation.tool_calls]
    recall = _multiset_recall(scenario.expected_tools, observed_names)
    precision = _tool_precision(
        scenario.expected_tools,
        scenario.optional_tools,
        observed_names,
    )
    forbidden = sum(
        name in set(scenario.forbidden_tools) for name in observed_names
    )
    invalid_arguments = sum(
        call.error_code == "invalid_arguments" for call in observation.tool_calls
    )

    if recall < 1:
        failures.append("missing_expected_tools")
    if precision < 1:
        failures.append("unexpected_tools")
    if forbidden:
        failures.append("forbidden_tool_called")
    if invalid_arguments:
        failures.append("invalid_tool_arguments")

    for invariant in scenario.argument_invariants:
        matching_calls = [
            call for call in observation.tool_calls if call.name == invariant.tool
        ]
        if not any(
            all(call.arguments.get(key) == value for key, value in invariant.contains.items())
            for call in matching_calls
        ):
            failures.append(f"argument_invariant_failed:{invariant.tool}")

    expected_final = scenario.final_state
    if observation.run_status is not expected_final.run_status:
        failures.append("wrong_run_status")
    if observation.step_count > scenario.max_steps:
        failures.append("max_steps_exceeded")

    library = {(entry.title, entry.status) for entry in observation.library}
    for entry in expected_final.library_contains:
        if (entry.title, entry.status) not in library:
            failures.append(f"library_missing:{entry.title}:{entry.status.value}")
    library_titles = {entry.title for entry in observation.library}
    for title in expected_final.library_excludes:
        if title in library_titles:
            failures.append(f"library_should_exclude:{title}")

    normalized_answer = (observation.final_answer or "").casefold()
    for fragment in expected_final.answer_contains:
        if fragment.casefold() not in normalized_answer:
            failures.append(f"answer_missing:{fragment}")

    return ScenarioEvaluation(
        scenario_id=scenario.id,
        run_id=observation.run_id,
        success=not failures,
        failures=failures,
        tool_precision=precision,
        tool_recall=recall,
        forbidden_calls=forbidden,
        invalid_argument_calls=invalid_arguments,
        step_count=observation.step_count,
        duration_ms=observation.duration_ms,
        input_tokens=observation.input_tokens,
        output_tokens=observation.output_tokens,
    )
