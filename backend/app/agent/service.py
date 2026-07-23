import json
from time import perf_counter
from uuid import UUID

from app.agent.repository import AgentRunRepository
from app.llm.models import Message, MessageRole
from app.llm.provider import LLMProvider
from app.models import AgentRun, AgentRunStatus
from app.tools.models import ToolResult
from app.tools.registry import ToolRegistry

AGENT_SYSTEM_PROMPT = (
    "Ты помощник по книгам. Используй доступные инструменты, "
    "когда для ответа нужны данные или действие."
)


def _tool_result_message(result: ToolResult) -> Message:
    return Message(
        role=MessageRole.TOOL,
        content=json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
        tool_call_id=result.tool_call_id,
        tool_name=result.tool_name,
    )


class AgentService:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        repository: AgentRunRepository,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._repository = repository

    def run(self, user_id: UUID, user_message: str) -> AgentRun:
        run = self._repository.create_run(user_id, user_message)
        messages = [
            Message(role=MessageRole.SYSTEM, content=AGENT_SYSTEM_PROMPT),
            Message(role=MessageRole.USER, content=user_message),
        ]
        step_number = 1

        while True:
            step_messages = [
                message.model_dump(mode="json") for message in messages
            ]
            started_at = perf_counter()
            response = self._provider.generate(
                messages,
                tools=self._registry.definitions(),
            )
            tool_results = [
                self._registry.execute(call) for call in response.tool_calls
            ]
            duration_ms = int((perf_counter() - started_at) * 1000)

            self._repository.add_step(
                run_id=run.id,
                step_number=step_number,
                messages=step_messages,
                response=response.model_dump(mode="json"),
                tool_results=[
                    result.model_dump(mode="json") for result in tool_results
                ],
                error=None,
                duration_ms=duration_ms,
            )

            if not response.tool_calls:
                run.status = AgentRunStatus.COMPLETED
                run.final_answer = response.text
                run.stop_reason = "final_response"
                self._repository.save_run(run)
                restored = self._repository.get_run(run.id)
                if restored is None:
                    raise RuntimeError("Saved agent run was not found")
                return restored

            messages.append(
                Message(
                    role=MessageRole.ASSISTANT,
                    content=response.text,
                    tool_calls=response.tool_calls,
                )
            )
            messages.extend(_tool_result_message(result) for result in tool_results)
            step_number += 1
