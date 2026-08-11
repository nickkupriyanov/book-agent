from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from app.agent.exceptions import (
    ApprovalConflictError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
)
from app.agent.repository import AgentRunRepository
from app.agent.state import AgentWorkingState, CompletedAction
from app.models import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
    PendingAction,
    PendingActionStatus,
)
from app.tools.models import ToolCall, ToolResult
from app.tools.policy import requires_approval
from app.tools.registry import PreparedToolCall, ToolRegistry


@dataclass(frozen=True)
class ApprovalOutcome:
    run: AgentRun
    action: PendingAction
    tool_result: ToolResult
    replayed: bool


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _find_proposal_step(run: AgentRun, tool_call_id: str) -> AgentStep:
    for step in reversed(run.steps):
        if step.response is None:
            continue
        calls = step.response.get("tool_calls", [])
        if any(call.get("id") == tool_call_id for call in calls):
            return step
    raise ApprovalConflictError("Approval proposal step was not found")


class ApprovalService:
    def __init__(
        self,
        registry: ToolRegistry,
        repository: AgentRunRepository,
    ) -> None:
        self._registry = registry
        self._repository = repository

    def approve(
        self,
        *,
        run_id: UUID,
        action_id: UUID,
        user_id: UUID,
    ) -> ApprovalOutcome:
        action = self._repository.get_action_for_user(
            run_id=run_id,
            action_id=action_id,
            user_id=user_id,
        )
        run = self._repository.get_run_for_user(run_id, user_id)
        if action is None or run is None:
            raise ApprovalNotFoundError("Approval action was not found")

        if action.status is PendingActionStatus.APPROVED:
            if action.result is None:
                raise ApprovalConflictError("Approved action has no saved result")
            return ApprovalOutcome(
                run=run,
                action=action,
                tool_result=ToolResult.model_validate(action.result),
                replayed=True,
            )

        if action.status is not PendingActionStatus.PENDING:
            raise ApprovalConflictError("Approval action is already resolved")
        if datetime.now(timezone.utc) >= _as_utc(action.expires_at):
            raise ApprovalExpiredError("Approval action has expired")
        if run.status is not AgentRunStatus.WAITING_FOR_APPROVAL:
            raise ApprovalConflictError("Agent run is not waiting for approval")
        if run.version != action.expected_run_version:
            raise ApprovalConflictError("Agent run version has changed")

        call = ToolCall(
            id=action.tool_call_id,
            name=action.tool_name,
            arguments=action.arguments,
        )
        prepared = self._registry.prepare(call)
        if not isinstance(prepared, PreparedToolCall):
            raise ApprovalConflictError("Saved tool call is no longer valid")
        if not requires_approval(prepared.definition.access):
            raise ApprovalConflictError("Saved tool no longer requires approval")

        proposal_step = _find_proposal_step(run, action.tool_call_id)
        try:
            tool_result = self._registry.execute_prepared(prepared)
            working_state = AgentWorkingState.model_validate(run.working_state)
            if tool_result.error is None:
                working_state = AgentWorkingState(
                    goal=working_state.goal,
                    completed_actions=[
                        *working_state.completed_actions,
                        CompletedAction(
                            step_number=proposal_step.step_number,
                            tool_call_id=action.tool_call_id,
                            tool_name=action.tool_name,
                        ),
                    ],
                    initial_step_budget=working_state.initial_step_budget,
                    remaining_step_budget=working_state.remaining_step_budget,
                )
            self._repository.complete_approval(
                run=run,
                action=action,
                proposal_step=proposal_step,
                tool_result=tool_result.model_dump(mode="json"),
                working_state=working_state.model_dump(mode="json"),
                resolved_at=datetime.now(timezone.utc),
            )
        except Exception:
            self._repository.rollback()
            raise

        restored_run = self._repository.get_run(run.id)
        restored_action = self._repository.get_action_for_user(
            run_id=run.id,
            action_id=action.id,
            user_id=user_id,
        )
        if restored_run is None or restored_action is None:
            raise RuntimeError("Approved action was not restored")
        return ApprovalOutcome(
            run=restored_run,
            action=restored_action,
            tool_result=tool_result,
            replayed=False,
        )
