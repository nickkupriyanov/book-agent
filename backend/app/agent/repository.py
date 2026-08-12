from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agent.state import AgentWorkingState
from app.models import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
    PendingAction,
    PendingActionStatus,
)


class AgentRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_run(
        self,
        user_id: UUID,
        user_message: str,
        working_state: AgentWorkingState,
    ) -> AgentRun:
        run = AgentRun(
            user_id=user_id,
            user_message=user_message,
            working_state=working_state.model_dump(mode="json"),
        )
        self._session.add(run)
        self._session.commit()
        self._session.refresh(run)
        return run

    def add_step(
        self,
        *,
        run_id: UUID,
        step_number: int,
        messages: list[dict[str, object]],
        response: dict[str, object] | None,
        tool_results: list[dict[str, object]],
        error: str | None,
        duration_ms: int,
    ) -> AgentStep:
        step = AgentStep(
            run_id=run_id,
            step_number=step_number,
            messages=messages,
            response=response,
            tool_results=tool_results,
            error=error,
            duration_ms=duration_ms,
        )
        self._session.add(step)
        self._session.commit()
        self._session.refresh(step)
        return step

    def save_run(self, run: AgentRun) -> AgentRun:
        run.version += 1
        self._session.commit()
        self._session.refresh(run)
        return run

    def get_run(self, run_id: UUID) -> AgentRun | None:
        statement = (
            select(AgentRun)
            .where(AgentRun.id == run_id)
            .options(
                selectinload(AgentRun.steps),
                selectinload(AgentRun.pending_actions),
            )
            .execution_options(populate_existing=True)
        )
        return self._session.scalar(statement)

    def get_run_for_user(
        self,
        run_id: UUID,
        user_id: UUID,
    ) -> AgentRun | None:
        statement = (
            select(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.user_id == user_id,
            )
            .options(
                selectinload(AgentRun.steps),
                selectinload(AgentRun.pending_actions),
            )
            .execution_options(populate_existing=True)
        )
        return self._session.scalar(statement)

    def pause_for_approval(
        self,
        *,
        run: AgentRun,
        step_number: int,
        messages: list[dict[str, object]],
        response: dict[str, object],
        duration_ms: int,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, object],
        summary: str,
        idempotency_key: str,
        expires_at: datetime,
    ) -> PendingAction:
        run.status = AgentRunStatus.WAITING_FOR_APPROVAL
        run.version += 1
        step = AgentStep(
            run_id=run.id,
            step_number=step_number,
            messages=messages,
            response=response,
            tool_results=[],
            error=None,
            duration_ms=duration_ms,
        )
        action = PendingAction(
            run_id=run.id,
            user_id=run.user_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            summary=summary,
            idempotency_key=idempotency_key,
            expires_at=expires_at,
            expected_run_version=run.version,
        )
        self._session.add_all([step, action])
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(run)
        self._session.refresh(step)
        self._session.refresh(action)
        return action

    def create_pending_action(
        self,
        *,
        run_id: UUID,
        user_id: UUID,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, object],
        summary: str,
        idempotency_key: str,
        expires_at: datetime,
        expected_run_version: int,
    ) -> PendingAction:
        action = PendingAction(
            run_id=run_id,
            user_id=user_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            summary=summary,
            idempotency_key=idempotency_key,
            expires_at=expires_at,
            expected_run_version=expected_run_version,
        )
        self._session.add(action)
        self._session.commit()
        self._session.refresh(action)
        return action

    def get_pending_action(self, action_id: UUID) -> PendingAction | None:
        return self._session.get(PendingAction, action_id)

    def get_action_for_user(
        self,
        *,
        run_id: UUID,
        action_id: UUID,
        user_id: UUID,
    ) -> PendingAction | None:
        statement = (
            select(PendingAction)
            .where(
                PendingAction.id == action_id,
                PendingAction.run_id == run_id,
                PendingAction.user_id == user_id,
            )
            .execution_options(populate_existing=True)
        )
        return self._session.scalar(statement)

    def get_pending_action_for_run(self, run_id: UUID) -> PendingAction | None:
        statement = select(PendingAction).where(
            PendingAction.run_id == run_id,
            PendingAction.status == PendingActionStatus.PENDING,
        )
        return self._session.scalar(statement)

    def complete_approval(
        self,
        *,
        run: AgentRun,
        action: PendingAction,
        proposal_step: AgentStep,
        tool_result: dict[str, object],
        working_state: dict[str, object],
        resolved_at: datetime,
    ) -> None:
        action.status = PendingActionStatus.APPROVED
        action.resolved_at = resolved_at
        action.result = tool_result
        proposal_step.tool_results = [tool_result]
        run.status = AgentRunStatus.RUNNING
        run.version += 1
        run.working_state = working_state
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def complete_rejection(
        self,
        *,
        run: AgentRun,
        action: PendingAction,
        proposal_step: AgentStep,
        tool_result: dict[str, object],
        resolved_at: datetime,
    ) -> None:
        action.status = PendingActionStatus.REJECTED
        action.resolved_at = resolved_at
        action.result = tool_result
        proposal_step.tool_results = [tool_result]
        run.status = AgentRunStatus.RUNNING
        run.version += 1
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def rollback(self) -> None:
        self._session.rollback()
