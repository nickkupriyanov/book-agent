from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CompletedAction(BaseModel):
    step_number: int = Field(ge=1)
    tool_call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentWorkingState(BaseModel):
    goal: str = Field(min_length=1)
    completed_actions: tuple[CompletedAction, ...] = ()
    initial_step_budget: int = Field(ge=1)
    remaining_step_budget: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_remaining_budget(self) -> Self:
        if self.remaining_step_budget > self.initial_step_budget:
            raise ValueError(
                "remaining_step_budget cannot exceed initial_step_budget"
            )
        return self
