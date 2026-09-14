from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.llm.models import ModelResponse
from app.models import AgentRunStatus, ReadingStatus


class InitialLibraryEntry(BaseModel):
    book_id: str
    status: ReadingStatus

    model_config = ConfigDict(extra="forbid")


class InitialNote(BaseModel):
    content: str = Field(min_length=1)
    book_id: str | None = None

    model_config = ConfigDict(extra="forbid")


class EvalInitialState(BaseModel):
    library: list[InitialLibraryEntry] = Field(default_factory=list)
    notes: list[InitialNote] = Field(default_factory=list)
    preferences: dict[str, JsonValue] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class ToolArgumentInvariant(BaseModel):
    tool: str = Field(min_length=1)
    contains: dict[str, JsonValue]

    model_config = ConfigDict(extra="forbid")


class ExpectedLibraryEntry(BaseModel):
    title: str = Field(min_length=1)
    status: ReadingStatus

    model_config = ConfigDict(extra="forbid")


class EvalFinalState(BaseModel):
    run_status: AgentRunStatus
    library_contains: list[ExpectedLibraryEntry] = Field(default_factory=list)
    library_excludes: list[str] = Field(default_factory=list)
    answer_contains: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class EvalScenario(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    input: str = Field(min_length=1)
    initial_state: EvalInitialState = Field(default_factory=EvalInitialState)
    expected_tools: list[str]
    optional_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str]
    argument_invariants: list[ToolArgumentInvariant] = Field(default_factory=list)
    final_state: EvalFinalState
    max_steps: int = Field(ge=1, le=20)
    fake_responses: list[ModelResponse] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_tool_groups_and_invariants(self) -> Self:
        expected = set(self.expected_tools)
        optional = set(self.optional_tools)
        forbidden = set(self.forbidden_tools)
        if expected & optional or expected & forbidden or optional & forbidden:
            raise ValueError("expected, optional, and forbidden tools must be disjoint")
        allowed = expected | optional
        if any(item.tool not in allowed for item in self.argument_invariants):
            raise ValueError("argument invariants require an expected or optional tool")
        if len(self.fake_responses) > self.max_steps:
            raise ValueError("fake responses cannot exceed max_steps")
        return self


class EvalDataset(BaseModel):
    version: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    scenarios: list[EvalScenario] = Field(min_length=20)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_unique_scenario_ids(self) -> Self:
        ids = [scenario.id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario IDs must be unique")
        return self


def load_dataset(path: Path) -> EvalDataset:
    return EvalDataset.model_validate_json(path.read_text(encoding="utf-8"))
