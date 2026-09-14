from datetime import datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    computed_field,
)

from app.agent.state import AgentWorkingState
from app.catalog.models import CatalogSource
from app.models import AgentRunStatus, PendingActionStatus, ReadingStatus
from app.tools.models import ToolResult


class HealthResponse(BaseModel):
    status: str


class AgentRunRequest(BaseModel):
    message: str = Field(min_length=1)


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogSearchTraceResponse(BaseModel):
    source: CatalogSource
    degraded: StrictBool
    cached: StrictBool

    model_config = ConfigDict(extra="forbid")


class AgentStepResponse(BaseModel):
    step_number: int
    messages: list[dict[str, object]]
    response: dict[str, object] | None
    tool_results: list[dict[str, object]]
    error: str | None
    duration_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def catalog_searches(self) -> list[CatalogSearchTraceResponse]:
        searches: list[CatalogSearchTraceResponse] = []
        for result in self.tool_results:
            if result.get("tool_name") != "search_books":
                continue
            output = result.get("output")
            if not isinstance(output, dict) or result.get("error") is not None:
                continue
            try:
                searches.append(
                    CatalogSearchTraceResponse.model_validate(
                        {
                            "source": output.get("source"),
                            "degraded": output.get("degraded"),
                            "cached": output.get("cached"),
                        }
                    )
                )
            except ValueError:
                continue
        return searches


class PendingActionResponse(BaseModel):
    id: UUID
    summary: str
    status: PendingActionStatus
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentRunResponse(BaseModel):
    id: UUID
    status: AgentRunStatus
    user_message: str
    provider_name: str
    model_name: str
    prompt_version: str
    working_state: AgentWorkingState
    final_answer: str | None
    stop_reason: str | None
    error: str | None
    pending_action: PendingActionResponse | None
    steps: list[AgentStepResponse]

    model_config = ConfigDict(from_attributes=True)


class ApprovalActionResponse(BaseModel):
    id: UUID
    status: PendingActionStatus
    resolved_at: datetime
    result: ToolResult

    model_config = ConfigDict(from_attributes=True)


class ApprovalResponse(BaseModel):
    action: ApprovalActionResponse
    run: AgentRunResponse
    replayed: bool


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


class NoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    book_id: UUID | None = None

    model_config = ConfigDict(extra="forbid")


class NoteUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    book_id: UUID | None = None

    model_config = ConfigDict(extra="forbid")


class NoteResponse(BaseModel):
    id: UUID
    book_id: UUID | None
    content: str
    revision: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PreferenceUpsert(BaseModel):
    value: JsonValue

    model_config = ConfigDict(extra="forbid")


class PreferenceResponse(BaseModel):
    key: str
    value: JsonValue
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
