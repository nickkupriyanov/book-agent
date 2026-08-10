from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agent.state import AgentWorkingState
from app.models import (
    AgentRun,
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
            .options(selectinload(AgentRun.steps))
            .execution_options(populate_existing=True)
        )
        return self._session.scalar(statement)

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

    def get_pending_action_for_run(self, run_id: UUID) -> PendingAction | None:
        statement = select(PendingAction).where(
            PendingAction.run_id == run_id,
            PendingAction.status == PendingActionStatus.PENDING,
        )
        return self._session.scalar(statement)
