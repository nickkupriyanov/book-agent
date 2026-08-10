import json
from datetime import datetime, timedelta, timezone
from time import perf_counter
from uuid import UUID

from app.agent.repository import AgentRunRepository
from app.agent.state import AgentWorkingState, CompletedAction
from app.llm.exceptions import (
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.models import Message, MessageRole, ModelResponse
from app.llm.provider import LLMProvider
from app.models import AgentRun, AgentRunStatus
from app.tools.models import (
    ToolCall,
    ToolError,
    ToolErrorCode,
    ToolResult,
)
from app.tools.policy import requires_approval
from app.tools.registry import PreparedToolCall, ToolRegistry

AGENT_SYSTEM_PROMPT = (
    "Ты помощник по книгам. Используй доступные инструменты, "
    "когда для ответа нужны данные или действие. Для рекомендаций сначала "
    "получи недавно завершённые книги пользователя, затем найди похожие. "
    "Используй только книги и идентификаторы из результатов инструментов, "
    "объясняй совпадения через matched_tags и не выдумывай недостающие "
    "варианты, если найдено меньше запрошенного количества."
)
WORKING_STATE_PREFIX = "\n\nРабочее состояние backend (только для чтения): "
PROVIDER_ERRORS = (
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)


def _tool_result_message(result: ToolResult) -> Message:
    return Message(
        role=MessageRole.TOOL,
        content=json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
        tool_call_id=result.tool_call_id,
        tool_name=result.tool_name,
    )


def _system_message(state: AgentWorkingState) -> Message:
    return Message(
        role=MessageRole.SYSTEM,
        content=(
            AGENT_SYSTEM_PROMPT
            + WORKING_STATE_PREFIX
            + json.dumps(
                state.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
            )
        ),
    )


def _consume_step_budget(state: AgentWorkingState) -> AgentWorkingState:
    return AgentWorkingState(
        goal=state.goal,
        completed_actions=state.completed_actions,
        initial_step_budget=state.initial_step_budget,
        remaining_step_budget=state.remaining_step_budget - 1,
    )


def _record_completed_action(
    state: AgentWorkingState,
    *,
    step_number: int,
    call: ToolCall,
) -> AgentWorkingState:
    return AgentWorkingState(
        goal=state.goal,
        completed_actions=[
            *state.completed_actions,
            CompletedAction(
                step_number=step_number,
                tool_call_id=call.id,
                tool_name=call.name,
            ),
        ],
        initial_step_budget=state.initial_step_budget,
        remaining_step_budget=state.remaining_step_budget,
    )


def _tool_call_signature(
    calls: list[ToolCall],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            call.name,
            json.dumps(
                call.arguments,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        for call in calls
    )


def _ambiguous_approval_result(call: ToolCall) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name=call.name,
        error=ToolError(
            code=ToolErrorCode.AMBIGUOUS_APPROVAL_BATCH,
            message="Approval-required tool calls must be submitted alone",
        ),
    )


class AgentService:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        repository: AgentRunRepository,
        max_steps: int = 5,
        approval_ttl_seconds: int = 900,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if approval_ttl_seconds < 1:
            raise ValueError("approval_ttl_seconds must be at least 1")
        self._provider = provider
        self._registry = registry
        self._repository = repository
        self._max_steps = max_steps
        self._approval_ttl_seconds = approval_ttl_seconds

    def _restored_run(self, run: AgentRun) -> AgentRun:
        restored = self._repository.get_run(run.id)
        if restored is None:
            raise RuntimeError("Saved agent run was not found")
        return restored

    def _fail_run(
        self,
        run: AgentRun,
        stop_reason: str,
        error: str,
    ) -> None:
        run.status = AgentRunStatus.FAILED
        run.stop_reason = stop_reason
        run.error = error
        self._repository.save_run(run)

    def _save_step(
        self,
        *,
        run: AgentRun,
        step_number: int,
        messages: list[dict[str, object]],
        response: ModelResponse | None,
        tool_results: list[ToolResult],
        error: str | None,
        started_at: float,
    ) -> None:
        self._repository.add_step(
            run_id=run.id,
            step_number=step_number,
            messages=messages,
            response=(
                response.model_dump(mode="json") if response is not None else None
            ),
            tool_results=[
                result.model_dump(mode="json") for result in tool_results
            ],
            error=error,
            duration_ms=int((perf_counter() - started_at) * 1000),
        )

    def _record_exception(
        self,
        *,
        run: AgentRun,
        step_number: int,
        messages: list[dict[str, object]],
        response: ModelResponse | None,
        tool_results: list[ToolResult],
        exception: Exception,
        stop_reason: str,
        started_at: float,
    ) -> None:
        error = type(exception).__name__
        self._save_step(
            run=run,
            step_number=step_number,
            messages=messages,
            response=response,
            tool_results=tool_results,
            error=error,
            started_at=started_at,
        )
        self._fail_run(run, stop_reason, error)

    def run(self, user_id: UUID, user_message: str) -> AgentRun:
        working_state = AgentWorkingState(
            goal=user_message,
            initial_step_budget=self._max_steps,
            remaining_step_budget=self._max_steps,
        )
        run = self._repository.create_run(
            user_id,
            user_message,
            working_state,
        )
        messages = [Message(role=MessageRole.USER, content=user_message)]
        previous_signature: tuple[tuple[str, str], ...] | None = None

        for step_number in range(1, self._max_steps + 1):
            provider_messages = [_system_message(working_state), *messages]
            step_messages = [
                message.model_dump(mode="json")
                for message in provider_messages
            ]
            started_at = perf_counter()
            try:
                response = self._provider.generate(
                    provider_messages,
                    tools=self._registry.definitions(),
                )
            except PROVIDER_ERRORS as exc:
                working_state = _consume_step_budget(working_state)
                run.working_state = working_state.model_dump(mode="json")
                self._record_exception(
                    run=run,
                    step_number=step_number,
                    messages=step_messages,
                    response=None,
                    tool_results=[],
                    exception=exc,
                    stop_reason="provider_error",
                    started_at=started_at,
                )
                raise
            except Exception as exc:
                working_state = _consume_step_budget(working_state)
                run.working_state = working_state.model_dump(mode="json")
                self._record_exception(
                    run=run,
                    step_number=step_number,
                    messages=step_messages,
                    response=None,
                    tool_results=[],
                    exception=exc,
                    stop_reason="unexpected_error",
                    started_at=started_at,
                )
                raise

            working_state = _consume_step_budget(working_state)
            run.working_state = working_state.model_dump(mode="json")
            signature = _tool_call_signature(response.tool_calls)
            if response.tool_calls and signature == previous_signature:
                error = "Repeated tool call"
                self._save_step(
                    run=run,
                    step_number=step_number,
                    messages=step_messages,
                    response=response,
                    tool_results=[],
                    error=error,
                    started_at=started_at,
                )
                self._fail_run(run, "repeated_tool_call", error)
                return self._restored_run(run)

            tool_results: list[ToolResult] = []
            try:
                prepared_calls = [
                    self._registry.prepare(call)
                    for call in response.tool_calls
                ]
                approval_calls = [
                    prepared
                    for prepared in prepared_calls
                    if isinstance(prepared, PreparedToolCall)
                    and requires_approval(prepared.definition.access)
                ]

                if approval_calls and len(response.tool_calls) != 1:
                    tool_results = [
                        _ambiguous_approval_result(call)
                        for call in response.tool_calls
                    ]
                elif approval_calls:
                    prepared = approval_calls[0]
                    summary = self._registry.summarize_for_approval(prepared)
                    if isinstance(summary, ToolResult):
                        tool_results = [summary]
                    else:
                        run.working_state = working_state.model_dump(mode="json")
                        self._repository.pause_for_approval(
                            run=run,
                            step_number=step_number,
                            messages=step_messages,
                            response=response.model_dump(mode="json"),
                            duration_ms=int(
                                (perf_counter() - started_at) * 1000
                            ),
                            tool_call_id=prepared.tool_call_id,
                            tool_name=prepared.definition.name,
                            arguments=prepared.canonical_arguments,
                            summary=summary,
                            idempotency_key=(
                                f"{run.id}:{prepared.tool_call_id}"
                            ),
                            expires_at=(
                                datetime.now(timezone.utc)
                                + timedelta(
                                    seconds=self._approval_ttl_seconds
                                )
                            ),
                        )
                        return self._restored_run(run)
                else:
                    for call, prepared in zip(
                        response.tool_calls,
                        prepared_calls,
                        strict=True,
                    ):
                        result = (
                            prepared
                            if isinstance(prepared, ToolResult)
                            else self._registry.execute_prepared(prepared)
                        )
                        tool_results.append(result)
                        if result.error is None:
                            working_state = _record_completed_action(
                                working_state,
                                step_number=step_number,
                                call=call,
                            )
            except Exception as exc:
                run.working_state = working_state.model_dump(mode="json")
                self._record_exception(
                    run=run,
                    step_number=step_number,
                    messages=step_messages,
                    response=response,
                    tool_results=tool_results,
                    exception=exc,
                    stop_reason="unexpected_error",
                    started_at=started_at,
                )
                raise

            run.working_state = working_state.model_dump(mode="json")
            self._save_step(
                run=run,
                step_number=step_number,
                messages=step_messages,
                response=response,
                tool_results=tool_results,
                error=None,
                started_at=started_at,
            )

            if not response.tool_calls:
                run.status = AgentRunStatus.COMPLETED
                run.final_answer = response.text
                run.stop_reason = "final_response"
                self._repository.save_run(run)
                return self._restored_run(run)

            previous_signature = signature
            messages.append(
                Message(
                    role=MessageRole.ASSISTANT,
                    content=response.text,
                    tool_calls=response.tool_calls,
                )
            )
            messages.extend(_tool_result_message(result) for result in tool_results)

        run.status = AgentRunStatus.STEP_LIMIT_EXCEEDED
        run.stop_reason = "max_steps"
        self._repository.save_run(run)
        return self._restored_run(run)
