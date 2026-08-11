from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.repository import AgentRunRepository
from app.agent.state import AgentWorkingState
from app.config import Settings
from app.models import AgentRunStatus, AgentStep, PendingActionStatus
from app.tools.library import RemoveBookArguments

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
BOOK_ID = UUID("10000000-0000-0000-0000-000000000001")


def make_working_state() -> AgentWorkingState:
    return AgentWorkingState(
        goal="Удали Дюну",
        initial_step_budget=5,
        remaining_step_budget=4,
    )


def test_pending_action_is_restored_in_a_new_session(session: Session) -> None:
    repository = AgentRunRepository(session)
    run = repository.create_run(USER_ID, "Удали Дюну", make_working_state())
    run.status = AgentRunStatus.WAITING_FOR_APPROVAL
    repository.save_run(run)
    expires_at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(
        minutes=15
    )
    action = repository.create_pending_action(
        run_id=run.id,
        user_id=USER_ID,
        tool_call_id="remove-1",
        tool_name="remove_book",
        arguments=RemoveBookArguments(book_id=BOOK_ID).model_dump(mode="json"),
        summary="Удалить «Дюну» из вашей библиотеки",
        idempotency_key=f"{run.id}:remove-1",
        expires_at=expires_at,
        expected_run_version=run.version,
    )

    with Session(session.get_bind()) as another_session:
        restored_repository = AgentRunRepository(another_session)
        restored = restored_repository.get_pending_action(action.id)
        restored_for_run = restored_repository.get_pending_action_for_run(run.id)

        assert restored is not None
        assert restored_for_run is not None
        assert restored_for_run.id == restored.id
        assert restored.run_id == run.id
        assert restored.user_id == USER_ID
        assert restored.tool_call_id == "remove-1"
        assert restored.tool_name == "remove_book"
        assert restored.arguments == {"book_id": str(BOOK_ID)}
        assert restored.summary == "Удалить «Дюну» из вашей библиотеки"
        assert restored.status is PendingActionStatus.PENDING
        assert restored.idempotency_key == f"{run.id}:remove-1"
        assert restored.expected_run_version == 1
        assert restored.expires_at.replace(tzinfo=timezone.utc) == expires_at
        assert restored.resolved_at is None
        assert restored.result is None
        restored_run = restored_repository.get_run(run.id)
        assert restored_run is not None
        assert restored_run.status is AgentRunStatus.WAITING_FOR_APPROVAL
        assert restored_run.version == 1


def test_database_allows_only_one_active_pending_action_per_run(
    session: Session,
) -> None:
    repository = AgentRunRepository(session)
    run = repository.create_run(USER_ID, "Удали Дюну", make_working_state())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    first = repository.create_pending_action(
        run_id=run.id,
        user_id=USER_ID,
        tool_call_id="remove-1",
        tool_name="remove_book",
        arguments={"book_id": str(BOOK_ID)},
        summary="Удалить «Дюну»",
        idempotency_key=f"{run.id}:remove-1",
        expires_at=expires_at,
        expected_run_version=0,
    )

    with pytest.raises(IntegrityError):
        repository.create_pending_action(
            run_id=run.id,
            user_id=USER_ID,
            tool_call_id="remove-2",
            tool_name="remove_book",
            arguments={"book_id": str(BOOK_ID)},
            summary="Снова удалить «Дюну»",
            idempotency_key=f"{run.id}:remove-2",
            expires_at=expires_at,
            expected_run_version=0,
        )

    session.rollback()
    first.status = PendingActionStatus.REJECTED
    first.resolved_at = datetime.now(timezone.utc)
    session.commit()

    next_action = repository.create_pending_action(
        run_id=run.id,
        user_id=USER_ID,
        tool_call_id="remove-3",
        tool_name="remove_book",
        arguments={"book_id": str(BOOK_ID)},
        summary="Удалить «Дюну» после нового предложения",
        idempotency_key=f"{run.id}:remove-3",
        expires_at=expires_at,
        expected_run_version=1,
    )

    assert next_action.status is PendingActionStatus.PENDING


def test_pending_action_ttl_has_safe_default_and_rejects_zero() -> None:
    assert Settings.model_fields["pending_action_ttl_seconds"].default == 900

    with pytest.raises(ValidationError):
        Settings(pending_action_ttl_seconds=0)


def test_idempotency_key_is_unique_across_runs(session: Session) -> None:
    repository = AgentRunRepository(session)
    first_run = repository.create_run(USER_ID, "Удали Дюну", make_working_state())
    second_run = repository.create_run(USER_ID, "Удали Дюну", make_working_state())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    shared_key = "remove-request-1"
    repository.create_pending_action(
        run_id=first_run.id,
        user_id=USER_ID,
        tool_call_id="remove-1",
        tool_name="remove_book",
        arguments={"book_id": str(BOOK_ID)},
        summary="Удалить «Дюну»",
        idempotency_key=shared_key,
        expires_at=expires_at,
        expected_run_version=0,
    )

    with pytest.raises(IntegrityError):
        repository.create_pending_action(
            run_id=second_run.id,
            user_id=USER_ID,
            tool_call_id="remove-2",
            tool_name="remove_book",
            arguments={"book_id": str(BOOK_ID)},
            summary="Удалить «Дюну»",
            idempotency_key=shared_key,
            expires_at=expires_at,
            expected_run_version=0,
        )


def test_pause_transaction_rolls_back_run_and_step_on_pending_conflict(
    session: Session,
) -> None:
    repository = AgentRunRepository(session)
    run = repository.create_run(USER_ID, "Удали Дюну", make_working_state())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    repository.create_pending_action(
        run_id=run.id,
        user_id=USER_ID,
        tool_call_id="existing-remove",
        tool_name="remove_book",
        arguments={"book_id": str(BOOK_ID)},
        summary="Существующее действие",
        idempotency_key=f"{run.id}:existing-remove",
        expires_at=expires_at,
        expected_run_version=0,
    )

    with pytest.raises(IntegrityError):
        repository.pause_for_approval(
            run=run,
            step_number=1,
            messages=[{"role": "user", "content": "Удали Дюну"}],
            response={
                "text": "",
                "tool_calls": [
                    {
                        "id": "new-remove",
                        "name": "remove_book",
                        "arguments": {"book_id": str(BOOK_ID)},
                    }
                ],
            },
            duration_ms=10,
            tool_call_id="new-remove",
            tool_name="remove_book",
            arguments={"book_id": str(BOOK_ID)},
            summary="Новое действие",
            idempotency_key=f"{run.id}:new-remove",
            expires_at=expires_at,
        )

    with Session(session.get_bind()) as another_session:
        restored = AgentRunRepository(another_session).get_run(run.id)
        assert restored is not None
        assert restored.status is AgentRunStatus.RUNNING
        assert restored.version == 0
        assert another_session.scalars(
            select(AgentStep).where(AgentStep.run_id == run.id)
        ).all() == []
        assert restored.pending_action is not None
        assert restored.pending_action.tool_call_id == "existing-remove"
