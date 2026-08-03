from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.agent.state import AgentWorkingState
from app.models import AgentRunStatus, ReadingStatus


class HealthResponse(BaseModel):
    status: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class AgentRunRequest(BaseModel):
    message: str = Field(min_length=1)


class AgentStepResponse(BaseModel):
    step_number: int
    messages: list[dict[str, object]]
    response: dict[str, object] | None
    tool_results: list[dict[str, object]]
    error: str | None
    duration_ms: int

    model_config = ConfigDict(from_attributes=True)


class AgentRunResponse(BaseModel):
    id: UUID
    status: AgentRunStatus
    user_message: str
    working_state: AgentWorkingState
    final_answer: str | None
    stop_reason: str | None
    error: str | None
    steps: list[AgentStepResponse]

    model_config = ConfigDict(from_attributes=True)


class BookResponse(BaseModel):
    id: UUID
    title: str
    author: str
    tags: list[str]

    model_config = ConfigDict(from_attributes=True)


class LibraryEntryCreate(BaseModel):
    book_id: UUID
    status: ReadingStatus


class LibraryStatusUpdate(BaseModel):
    status: ReadingStatus


class LibraryEntryResponse(BaseModel):
    book: BookResponse
    status: ReadingStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
