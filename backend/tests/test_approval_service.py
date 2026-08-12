from datetime import datetime, timedelta, timezone
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
    action.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()

    with pytest.raises(ApprovalExpiredError):
        ApprovalService(registry, repository).approve(
            run_id=run.id,
            action_id=action.id,
            user_id=USER_ID,
        )

    handler.assert_not_called()


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
