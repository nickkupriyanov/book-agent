from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.agent.approval import ApprovalService
from app.agent.exceptions import (
    ApprovalConflictError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
)
from app.agent.repository import AgentRunRepository
from app.agent.service import AgentService
from app.agent.state import AgentWorkingState
from app.llm.fake import FakeLLMProvider
from app.llm.models import ModelResponse
from app.models import AgentRunStatus, PendingActionStatus, ReadingStatus
from app.repository import BookRepository
from app.service import BookService
from app.tools.library import (
    REMOVE_BOOK_TOOL,
    RemoveBookApprovalSummary,
    RemoveBookHandler,
)
from app.tools.models import ToolCall
from app.tools.registry import ToolRegistry

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")


def create_waiting_action(session: Session):
    book_service = BookService(BookRepository(session))
    book_service.add_book(USER_ID, DUNE_ID, ReadingStatus.READING)
    remove_handler = Mock(
        wraps=RemoveBookHandler(book_service, USER_ID, commit=False)
    )
    registry = ToolRegistry()
    registry.register(
        REMOVE_BOOK_TOOL,
        remove_handler,
        approval_summary=RemoveBookApprovalSummary(book_service, USER_ID),
    )
    repository = AgentRunRepository(session)
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="remove-1",
                        name="remove_book",
                        arguments={"book_id": str(DUNE_ID)},
                    )
                ],
            )
        ]
    )
    run = AgentService(provider, registry, repository).run(
        USER_ID,
        "Удали Дюну",
    )
    assert run.pending_action is not None
    return (
        book_service,
        remove_handler,
        registry,
        repository,
        run,
        run.pending_action,
    )


def test_approve_executes_saved_arguments_and_replay_is_stable(
    session: Session,
) -> None:
    (
        book_service,
        remove_handler,
        registry,
        repository,
        run,
        action,
    ) = create_waiting_action(session)
    service = ApprovalService(registry, repository)

    first = service.approve(
        run_id=run.id,
        action_id=action.id,
        user_id=USER_ID,
    )
    replay = service.approve(
        run_id=run.id,
        action_id=action.id,
        user_id=USER_ID,
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.tool_result == first.tool_result
    assert first.action.status is PendingActionStatus.APPROVED
    assert first.action.result == first.tool_result.model_dump(mode="json")
    assert first.action.resolved_at is not None
    assert first.run.status is AgentRunStatus.RUNNING
    assert first.run.version == 2
    assert first.run.steps[0].tool_results == [first.action.result]
    state = AgentWorkingState.model_validate(first.run.working_state)
    assert [item.tool_call_id for item in state.completed_actions] == ["remove-1"]
    assert book_service.get_library(USER_ID) == []
    remove_handler.assert_called_once()


def test_approve_rolls_back_effect_and_resolution_when_commit_fails(
    session: Session,
) -> None:
    (
        _,
        remove_handler,
        registry,
        repository,
        run,
        action,
    ) = create_waiting_action(session)
    original_commit = session.commit
    session.commit = Mock(side_effect=RuntimeError("commit failed"))

    with pytest.raises(RuntimeError, match="commit failed"):
        ApprovalService(registry, repository).approve(
            run_id=run.id,
            action_id=action.id,
            user_id=USER_ID,
        )

    session.commit = original_commit
    with Session(session.get_bind()) as another_session:
        restored_repository = AgentRunRepository(another_session)
        restored_run = restored_repository.get_run(run.id)
        restored_action = restored_repository.get_action_for_user(
            run_id=run.id,
            action_id=action.id,
            user_id=USER_ID,
        )
        restored_book_service = BookService(BookRepository(another_session))

        assert restored_run is not None
        assert restored_action is not None
        assert restored_run.status is AgentRunStatus.WAITING_FOR_APPROVAL
        assert restored_run.version == 1
        assert restored_run.steps[0].tool_results == []
        assert restored_action.status is PendingActionStatus.PENDING
        assert restored_action.result is None
        assert restored_action.resolved_at is None
        assert len(restored_book_service.get_library(USER_ID)) == 1
    remove_handler.assert_called_once()


def test_approve_rejects_expired_action_before_handler(session: Session) -> None:
    _, handler, registry, repository, run, action = create_waiting_action(session)
    now = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
    action.expires_at = now - timedelta(seconds=1)
    session.commit()

    with pytest.raises(ApprovalExpiredError):
        ApprovalService(registry, repository, clock=lambda: now).approve(
            run_id=run.id,
            action_id=action.id,
            user_id=USER_ID,
        )

    handler.assert_not_called()

    with Session(session.get_bind()) as restarted_session:
        restarted_repository = AgentRunRepository(restarted_session)
        restored_run = restarted_repository.get_run(run.id)
        restored_action = restarted_repository.get_action_for_user(
            run_id=run.id,
            action_id=action.id,
            user_id=USER_ID,
        )

        assert restored_run is not None
        assert restored_action is not None
        assert restored_action.status is PendingActionStatus.EXPIRED
        assert _as_utc_for_test(restored_action.resolved_at) == now
        assert restored_run.status is AgentRunStatus.FAILED
        assert restored_run.stop_reason == "approval_expired"
        assert restored_run.version == 2

        with pytest.raises(ApprovalExpiredError):
            ApprovalService(
                registry,
                restarted_repository,
                clock=lambda: now + timedelta(minutes=1),
            ).reject(
                run_id=run.id,
                action_id=action.id,
                user_id=USER_ID,
            )


def _as_utc_for_test(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def test_approve_rejects_changed_run_version_before_handler(
    session: Session,
) -> None:
    _, handler, registry, repository, run, action = create_waiting_action(session)
    run.version += 1
    session.commit()

    with pytest.raises(ApprovalConflictError, match="version"):
        ApprovalService(registry, repository).approve(
            run_id=run.id,
            action_id=action.id,
            user_id=USER_ID,
        )

    handler.assert_not_called()


def test_approve_rejects_run_that_is_no_longer_waiting(session: Session) -> None:
    _, handler, registry, repository, run, action = create_waiting_action(session)
    run.status = AgentRunStatus.COMPLETED
    session.commit()

    with pytest.raises(ApprovalConflictError, match="not waiting"):
        ApprovalService(registry, repository).approve(
            run_id=run.id,
            action_id=action.id,
            user_id=USER_ID,
        )

    handler.assert_not_called()


def test_approve_revalidates_saved_arguments_before_handler(
    session: Session,
) -> None:
    _, handler, registry, repository, run, action = create_waiting_action(session)
    action.arguments = {"book_id": "not-a-uuid"}
    session.commit()

    with pytest.raises(ApprovalConflictError, match="no longer valid"):
        ApprovalService(registry, repository).approve(
            run_id=run.id,
            action_id=action.id,
            user_id=USER_ID,
        )

    handler.assert_not_called()


def test_approve_hides_action_from_another_user(session: Session) -> None:
    _, handler, registry, repository, run, action = create_waiting_action(session)

    with pytest.raises(ApprovalNotFoundError):
        ApprovalService(registry, repository).approve(
            run_id=run.id,
            action_id=action.id,
            user_id=uuid4(),
        )

    handler.assert_not_called()


def test_missing_and_foreign_actions_have_the_same_error(session: Session) -> None:
    _, handler, registry, repository, run, action = create_waiting_action(session)
    service = ApprovalService(registry, repository)

    errors = []
    for action_id, user_id in ((uuid4(), USER_ID), (action.id, uuid4())):
        with pytest.raises(ApprovalNotFoundError) as exc_info:
            service.reject(
                run_id=run.id,
                action_id=action_id,
                user_id=user_id,
            )
        errors.append(str(exc_info.value))

    assert errors == ["Approval action was not found"] * 2
    handler.assert_not_called()


def test_reject_requires_tool_to_remain_registered_as_destructive(
    session: Session,
) -> None:
    _, handler, _, repository, run, action = create_waiting_action(session)

    with pytest.raises(ApprovalConflictError, match="no longer requires approval"):
        ApprovalService(ToolRegistry(), repository).reject(
            run_id=run.id,
            action_id=action.id,
            user_id=USER_ID,
        )

    handler.assert_not_called()


def test_reject_persists_result_without_executing_handler_and_replays(
    session: Session,
) -> None:
    (
        book_service,
        remove_handler,
        registry,
        repository,
        run,
        action,
    ) = create_waiting_action(session)
    action.arguments = {"book_id": "corrupted-but-never-executed"}
    session.commit()
    service = ApprovalService(registry, repository)

    with pytest.raises(ApprovalNotFoundError):
        service.reject(
            run_id=run.id,
            action_id=action.id,
            user_id=uuid4(),
        )
    remove_handler.assert_not_called()

    first = service.reject(
        run_id=run.id,
        action_id=action.id,
        user_id=USER_ID,
    )
    replay = service.reject(
        run_id=run.id,
        action_id=action.id,
        user_id=USER_ID,
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.tool_result == first.tool_result
    assert first.action.status is PendingActionStatus.REJECTED
    assert first.action.resolved_at is not None
    assert first.action.result == first.tool_result.model_dump(mode="json")
    assert first.tool_result.error is not None
    assert first.tool_result.error.code.value == "user_rejected"
    assert first.run.status is AgentRunStatus.RUNNING
    assert first.run.version == 2
    assert first.run.steps[0].tool_results == [first.action.result]
    state = AgentWorkingState.model_validate(first.run.working_state)
    assert state.completed_actions == ()
    assert len(book_service.get_library(USER_ID)) == 1
    remove_handler.assert_not_called()


def test_reject_rolls_back_decision_and_trace_when_commit_fails(
    session: Session,
) -> None:
    (
        book_service,
        remove_handler,
        registry,
        repository,
        run,
        action,
    ) = create_waiting_action(session)
    original_commit = session.commit
    session.commit = Mock(side_effect=RuntimeError("commit failed"))

    with pytest.raises(RuntimeError, match="commit failed"):
        ApprovalService(registry, repository).reject(
            run_id=run.id,
            action_id=action.id,
            user_id=USER_ID,
        )

    session.commit = original_commit
    with Session(session.get_bind()) as another_session:
        restored_repository = AgentRunRepository(another_session)
        restored_run = restored_repository.get_run(run.id)
        restored_action = restored_repository.get_action_for_user(
            run_id=run.id,
            action_id=action.id,
            user_id=USER_ID,
        )

        assert restored_run is not None
        assert restored_action is not None
        assert restored_run.status is AgentRunStatus.WAITING_FOR_APPROVAL
        assert restored_run.version == 1
        assert restored_run.steps[0].tool_results == []
        assert restored_action.status is PendingActionStatus.PENDING
        assert restored_action.result is None
        assert restored_action.resolved_at is None
    assert len(book_service.get_library(USER_ID)) == 1
    remove_handler.assert_not_called()


def test_resolved_decision_cannot_be_changed(session: Session) -> None:
    _, handler, registry, repository, run, action = create_waiting_action(session)
    service = ApprovalService(registry, repository)
    rejected = service.reject(
        run_id=run.id,
        action_id=action.id,
        user_id=USER_ID,
    )

    with pytest.raises(ApprovalConflictError, match="already resolved"):
        service.approve(
            run_id=run.id,
            action_id=action.id,
            user_id=USER_ID,
        )

    assert rejected.action.status is PendingActionStatus.REJECTED
    handler.assert_not_called()

    another_run = AgentService(
        FakeLLMProvider(
            [
                ModelResponse(
                    text="",
                    tool_calls=[
                        ToolCall(
                            id="remove-2",
                            name="remove_book",
                            arguments={"book_id": str(DUNE_ID)},
                        )
                    ],
                )
            ]
        ),
        registry,
        repository,
    ).run(USER_ID, "Удали Дюну снова")
    assert another_run.pending_action is not None
    another_action_id = another_run.pending_action.id
    approved = service.approve(
        run_id=another_run.id,
        action_id=another_action_id,
        user_id=USER_ID,
    )

    with pytest.raises(ApprovalConflictError, match="already resolved"):
        service.reject(
            run_id=another_run.id,
            action_id=another_action_id,
            user_id=USER_ID,
        )

    assert approved.action.status is PendingActionStatus.APPROVED
    handler.assert_called_once()


def test_approve_replay_survives_a_new_session(session: Session) -> None:
    _, handler, registry, repository, run, action = create_waiting_action(session)
    first = ApprovalService(registry, repository).approve(
        run_id=run.id,
        action_id=action.id,
        user_id=USER_ID,
    )

    with Session(session.get_bind()) as restarted_session:
        replay = ApprovalService(
            ToolRegistry(),
            AgentRunRepository(restarted_session),
        ).approve(
            run_id=run.id,
            action_id=action.id,
            user_id=USER_ID,
        )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.tool_result == first.tool_result
    handler.assert_called_once()


def test_two_concurrent_approvals_execute_handler_once(session: Session) -> None:
    _, _, _, _, run, action = create_waiting_action(session)
    bind = session.get_bind()
    start_together = Barrier(2)
    calls: list[str] = []
    calls_lock = Lock()
    fixed_now = datetime.now(timezone.utc)

    def approve_in_independent_session():
        with Session(bind) as worker_session:
            book_service = BookService(BookRepository(worker_session))
            remove = RemoveBookHandler(book_service, USER_ID, commit=False)

            def counted_handler(arguments):
                with calls_lock:
                    calls.append("remove")
                return remove(arguments)

            worker_registry = ToolRegistry()
            worker_registry.register(
                REMOVE_BOOK_TOOL,
                counted_handler,
                approval_summary=RemoveBookApprovalSummary(
                    book_service,
                    USER_ID,
                ),
            )

            def synchronized_clock() -> datetime:
                start_together.wait(timeout=5)
                return fixed_now

            return ApprovalService(
                worker_registry,
                AgentRunRepository(worker_session),
                clock=synchronized_clock,
            ).approve(
                run_id=run.id,
                action_id=action.id,
                user_id=USER_ID,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: approve_in_independent_session(), range(2)))

    assert sorted(outcome.replayed for outcome in outcomes) == [False, True]
    assert calls == ["remove"]

    with Session(bind) as verification_session:
        restored = AgentRunRepository(verification_session).get_run(run.id)
        assert restored is not None
        assert restored.version == 2
        assert restored.pending_actions[0].status is PendingActionStatus.APPROVED
        assert BookService(BookRepository(verification_session)).get_library(USER_ID) == []
