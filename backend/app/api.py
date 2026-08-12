from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.agent.repository import AgentRunRepository
from app.agent.approval import ApprovalService
from app.agent.service import AgentService
from app.config import Settings, get_settings
from app.dependencies import (
    get_agent_repository,
    get_agent_service,
    get_approval_service,
    get_book_service,
    get_chat_service,
)
from app.llm.models import ModelResponse
from app.llm.service import ChatService
from app.models import ReadingStatus
from app.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    ApprovalActionResponse,
    ApprovalDecisionRequest,
    ApprovalResponse,
    BookResponse,
    ChatRequest,
    LibraryEntryCreate,
    LibraryEntryResponse,
    LibraryStatusUpdate,
)
from app.service import BookService

router = APIRouter(prefix="/api")


@router.post(
    "/chat",
    response_model=ModelResponse,
    response_model_exclude={"tool_calls"},
)
def chat(
    payload: ChatRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ModelResponse:
    return service.reply(payload.message)


@router.post(
    "/agent/runs",
    response_model=AgentRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_agent_run(
    payload: AgentRunRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentRunResponse:
    run = service.run(settings.demo_user_id, payload.message)
    return AgentRunResponse.model_validate(run)


@router.get(
    "/agent/runs/{run_id}",
    response_model=AgentRunResponse,
)
def get_agent_run(
    run_id: UUID,
    repository: Annotated[
        AgentRunRepository,
        Depends(get_agent_repository),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentRunResponse:
    run = repository.get_run_for_user(run_id, settings.demo_user_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return AgentRunResponse.model_validate(run)


@router.post(
    "/agent/runs/{run_id}/actions/{action_id}/approve",
    response_model=ApprovalResponse,
)
def approve_agent_action(
    run_id: UUID,
    action_id: UUID,
    payload: ApprovalDecisionRequest,
    approval_service: Annotated[
        ApprovalService,
        Depends(get_approval_service),
    ],
    agent_service: Annotated[AgentService, Depends(get_agent_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApprovalResponse:
    outcome = approval_service.approve(
        run_id=run_id,
        action_id=action_id,
        user_id=settings.demo_user_id,
    )
    run = (
        outcome.run
        if outcome.replayed
        else agent_service.resume(run_id, outcome.tool_result)
    )
    return ApprovalResponse(
        action=ApprovalActionResponse.model_validate(outcome.action),
        run=AgentRunResponse.model_validate(run),
        replayed=outcome.replayed,
    )


@router.post(
    "/agent/runs/{run_id}/actions/{action_id}/reject",
    response_model=ApprovalResponse,
)
def reject_agent_action(
    run_id: UUID,
    action_id: UUID,
    payload: ApprovalDecisionRequest,
    approval_service: Annotated[
        ApprovalService,
        Depends(get_approval_service),
    ],
    agent_service: Annotated[AgentService, Depends(get_agent_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApprovalResponse:
    outcome = approval_service.reject(
        run_id=run_id,
        action_id=action_id,
        user_id=settings.demo_user_id,
    )
    run = (
        outcome.run
        if outcome.replayed
        else agent_service.resume(run_id, outcome.tool_result)
    )
    return ApprovalResponse(
        action=ApprovalActionResponse.model_validate(outcome.action),
        run=AgentRunResponse.model_validate(run),
        replayed=outcome.replayed,
    )


@router.get("/books/search", response_model=list[BookResponse])
def search_books(
    service: Annotated[BookService, Depends(get_book_service)],
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[BookResponse]:
    return service.search_books(query=q, limit=limit)


@router.get("/books/{book_id}", response_model=BookResponse)
def get_book(
    book_id: UUID,
    service: Annotated[BookService, Depends(get_book_service)],
) -> BookResponse:
    return service.get_book(book_id)


@router.get("/library", response_model=list[LibraryEntryResponse])
def get_library(
    service: Annotated[BookService, Depends(get_book_service)],
    status_filter: Annotated[ReadingStatus | None, Query(alias="status")] = None,
) -> list[LibraryEntryResponse]:
    return service.get_library(get_settings().demo_user_id, status_filter)


@router.post(
    "/library",
    response_model=LibraryEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_library_entry(
    payload: LibraryEntryCreate,
    service: Annotated[BookService, Depends(get_book_service)],
) -> LibraryEntryResponse:
    return service.add_book(
        user_id=get_settings().demo_user_id,
        book_id=payload.book_id,
        status=payload.status,
    )


@router.patch(
    "/library/{book_id}/status",
    response_model=LibraryEntryResponse,
)
def update_library_status(
    book_id: UUID,
    payload: LibraryStatusUpdate,
    service: Annotated[BookService, Depends(get_book_service)],
) -> LibraryEntryResponse:
    return service.update_status(
        user_id=get_settings().demo_user_id,
        book_id=book_id,
        status=payload.status,
    )
