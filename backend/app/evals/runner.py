from collections.abc import Callable
from datetime import datetime, timezone
from statistics import mean
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.repository import AgentRunRepository
from app.agent.service import AgentService
from app.evals.evaluator import (
    ObservedLibraryEntry,
    ObservedToolCall,
    ScenarioEvaluation,
    ScenarioObservation,
    evaluate_scenario,
)
from app.evals.models import EvalDataset, EvalScenario
from app.llm.fake import FakeLLMProvider
from app.llm.provider import LLMProvider
from app.memory.repository import MemoryRepository
from app.memory.service import MemoryService
from app.models import Base, AgentRun
from app.observability import build_safe_trace
from app.repository import BookRepository
from app.seed import seed_database
from app.service import BookService
from app.tools.books import SEARCH_BOOKS_TOOL, SearchBooksHandler
from app.tools.library import (
    ADD_BOOK_TOOL,
    GET_USER_LIBRARY_TOOL,
    REMOVE_BOOK_TOOL,
    UPDATE_BOOK_STATUS_TOOL,
    AddBookHandler,
    GetUserLibraryHandler,
    RemoveBookApprovalSummary,
    RemoveBookHandler,
    UpdateBookStatusHandler,
)
from app.tools.memory import SEARCH_USER_NOTES_TOOL, SearchUserNotesHandler
from app.tools.models import ToolCall
from app.tools.recommendations import (
    FIND_SIMILAR_BOOKS_TOOL,
    FindSimilarBooksHandler,
)
from app.tools.registry import ToolRegistry

EVAL_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
ProviderFactory = Callable[[EvalScenario], LLMProvider]


class EvalMetrics(BaseModel):
    scenario_count: int = Field(ge=0)
    successful_scenarios: int = Field(ge=0)
    task_success_rate: float = Field(ge=0, le=1)
    mean_tool_precision: float = Field(ge=0, le=1)
    mean_tool_recall: float = Field(ge=0, le=1)
    forbidden_calls: int = Field(ge=0)
    invalid_argument_calls: int = Field(ge=0)
    total_steps: int = Field(ge=0)
    mean_steps: float = Field(ge=0)
    total_duration_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")


class EvalReport(BaseModel):
    dataset_version: str
    prompt_version: str
    provider: str
    model: str
    generated_at: datetime
    metrics: EvalMetrics
    scenarios: list[ScenarioEvaluation]

    model_config = ConfigDict(extra="forbid")


def _registry(
    book_service: BookService,
    memory_service: MemoryService,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(SEARCH_BOOKS_TOOL, SearchBooksHandler(book_service))
    registry.register(
        FIND_SIMILAR_BOOKS_TOOL,
        FindSimilarBooksHandler(book_service, EVAL_USER_ID),
    )
    registry.register(
        GET_USER_LIBRARY_TOOL,
        GetUserLibraryHandler(book_service, EVAL_USER_ID),
    )
    registry.register(ADD_BOOK_TOOL, AddBookHandler(book_service, EVAL_USER_ID))
    registry.register(
        UPDATE_BOOK_STATUS_TOOL,
        UpdateBookStatusHandler(book_service, EVAL_USER_ID),
    )
    registry.register(
        SEARCH_USER_NOTES_TOOL,
        SearchUserNotesHandler(memory_service, EVAL_USER_ID),
    )
    registry.register(
        REMOVE_BOOK_TOOL,
        RemoveBookHandler(book_service, EVAL_USER_ID, commit=False),
        approval_summary=RemoveBookApprovalSummary(book_service, EVAL_USER_ID),
    )
    return registry


def _prepare_initial_state(
    scenario: EvalScenario,
    book_service: BookService,
    memory_service: MemoryService,
) -> None:
    for entry in scenario.initial_state.library:
        book_service.add_book(EVAL_USER_ID, UUID(entry.book_id), entry.status)
    for note in scenario.initial_state.notes:
        memory_service.create_note(
            EVAL_USER_ID,
            note.content,
            UUID(note.book_id) if note.book_id is not None else None,
        )
    for key, value in scenario.initial_state.preferences.items():
        memory_service.set_preference(EVAL_USER_ID, key, value)


def _observation(
    run: AgentRun,
    book_service: BookService,
) -> ScenarioObservation:
    tool_calls: list[ObservedToolCall] = []
    input_tokens: int | None = None
    output_tokens: int | None = None
    for step in run.steps:
        errors_by_call_id = {
            result["tool_call_id"]: (
                result.get("error", {}).get("code")
                if isinstance(result.get("error"), dict)
                else None
            )
            for result in step.tool_results
        }
        if step.response is None:
            continue
        for raw_call in step.response.get("tool_calls", []):
            call = ToolCall.model_validate(raw_call)
            tool_calls.append(
                ObservedToolCall(
                    name=call.name,
                    arguments=call.arguments,
                    error_code=errors_by_call_id.get(call.id),
                )
            )
        usage = step.response.get("usage")
        if isinstance(usage, dict):
            input_tokens = (input_tokens or 0) + int(usage.get("input_tokens", 0))
            output_tokens = (output_tokens or 0) + int(
                usage.get("output_tokens", 0)
            )

    return ScenarioObservation(
        run_id=run.id,
        run_status=run.status,
        final_answer=run.final_answer,
        tool_calls=tool_calls,
        library=[
            ObservedLibraryEntry(title=entry.book.title, status=entry.status)
            for entry in book_service.get_library(EVAL_USER_ID)
        ],
        step_count=len(run.steps),
        duration_ms=sum(step.duration_ms for step in run.steps),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def run_scenario(
    scenario: EvalScenario,
    provider: LLMProvider,
    *,
    provider_name: str = "fake",
    model_name: str = "scripted",
    prompt_version: str = "book-agent-system-v1",
) -> ScenarioEvaluation:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            seed_database(session)
            book_service = BookService(BookRepository(session))
            memory_service = MemoryService(MemoryRepository(session))
            _prepare_initial_state(scenario, book_service, memory_service)
            run = AgentService(
                provider,
                _registry(book_service, memory_service),
                AgentRunRepository(session),
                max_steps=scenario.max_steps,
                provider_name=provider_name,
                model_name=model_name,
                prompt_version=prompt_version,
            ).run(EVAL_USER_ID, scenario.input)
            evaluation = evaluate_scenario(
                scenario,
                _observation(run, book_service),
            )
            return evaluation.model_copy(
                update={"safe_trace": build_safe_trace(run)}
            )
    finally:
        engine.dispose()


def _metrics(results: list[ScenarioEvaluation]) -> EvalMetrics:
    count = len(results)
    tokens_available = any(result.input_tokens is not None for result in results)
    return EvalMetrics(
        scenario_count=count,
        successful_scenarios=sum(result.success for result in results),
        task_success_rate=(sum(result.success for result in results) / count),
        mean_tool_precision=mean(result.tool_precision for result in results),
        mean_tool_recall=mean(result.tool_recall for result in results),
        forbidden_calls=sum(result.forbidden_calls for result in results),
        invalid_argument_calls=sum(
            result.invalid_argument_calls for result in results
        ),
        total_steps=sum(result.step_count for result in results),
        mean_steps=mean(result.step_count for result in results),
        total_duration_ms=sum(result.duration_ms for result in results),
        input_tokens=(
            sum(result.input_tokens or 0 for result in results)
            if tokens_available
            else None
        ),
        output_tokens=(
            sum(result.output_tokens or 0 for result in results)
            if tokens_available
            else None
        ),
    )


def run_dataset(
    dataset: EvalDataset,
    *,
    provider_factory: ProviderFactory | None = None,
    provider_name: str = "fake",
    model_name: str = "scripted",
) -> EvalReport:
    factory = provider_factory or (
        lambda scenario: FakeLLMProvider(scenario.fake_responses)
    )
    results = [
        run_scenario(
            scenario,
            factory(scenario),
            provider_name=provider_name,
            model_name=model_name,
            prompt_version=dataset.prompt_version,
        )
        for scenario in dataset.scenarios
    ]
    return EvalReport(
        dataset_version=dataset.version,
        prompt_version=dataset.prompt_version,
        provider=provider_name,
        model=model_name,
        generated_at=datetime.now(timezone.utc),
        metrics=_metrics(results),
        scenarios=results,
    )
