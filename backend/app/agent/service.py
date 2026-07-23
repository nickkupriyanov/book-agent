import json
from time import perf_counter
from uuid import UUID

from app.agent.repository import AgentRunRepository
from app.llm.exceptions import (
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.models import Message, MessageRole, ModelResponse
from app.llm.provider import LLMProvider
from app.models import AgentRun, AgentRunStatus
from app.tools.models import ToolCall, ToolResult
from app.tools.registry import ToolRegistry

AGENT_SYSTEM_PROMPT = (
    "Ты помощник по книгам. Используй доступные инструменты, "
    "когда для ответа нужны данные или действие."
)
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


class AgentService:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        repository: AgentRunRepository,
        max_steps: int = 5,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self._provider = provider
        self._registry = registry
        self._repository = repository
        self._max_steps = max_steps

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
        run = self._repository.create_run(user_id, user_message)
        messages = [
            Message(role=MessageRole.SYSTEM, content=AGENT_SYSTEM_PROMPT),
            Message(role=MessageRole.USER, content=user_message),
        ]
        previous_signature: tuple[tuple[str, str], ...] | None = None

        for step_number in range(1, self._max_steps + 1):
            step_messages = [
                message.model_dump(mode="json") for message in messages
            ]
            started_at = perf_counter()
            try:
                response = self._provider.generate(
                    messages,
                    tools=self._registry.definitions(),
                )
            except PROVIDER_ERRORS as exc:
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
                for call in response.tool_calls:
                    tool_results.append(self._registry.execute(call))
            except Exception as exc:
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
