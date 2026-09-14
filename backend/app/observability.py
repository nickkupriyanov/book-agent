import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.models import AgentRun, AgentRunStatus
from app.tools.models import ToolCall

REDACTED = "[REDACTED]"
CONTENT_KEYS = {"content", "fragment"}
SECRET_KEYS = {
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
}
SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(?:bearer\s+\S+|sk-[a-z0-9_-]{8,})"
)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return normalized in CONTENT_KEYS or normalized in SECRET_KEYS or any(
        normalized.endswith(f"_{suffix}")
        for suffix in ("api_key", "password", "secret", "access_token")
    )


def redact(value: JsonValue, *, key: str | None = None) -> JsonValue:
    if key is not None and _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {item_key: redact(item, key=item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and SECRET_VALUE_PATTERN.search(value):
        return REDACTED
    return value


class SafeToolTrace(BaseModel):
    name: str
    arguments: dict[str, JsonValue]
    result: dict[str, JsonValue] | None
    error: dict[str, JsonValue] | None

    model_config = ConfigDict(extra="forbid")


class SafeStepTrace(BaseModel):
    step_number: int = Field(ge=1)
    duration_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    error: str | None
    tools: list[SafeToolTrace]

    model_config = ConfigDict(extra="forbid")


class SafeRunTrace(BaseModel):
    run_id: UUID
    status: AgentRunStatus
    provider: str
    model: str
    prompt_version: str
    steps: list[SafeStepTrace]

    model_config = ConfigDict(extra="forbid")


def build_safe_trace(run: AgentRun) -> SafeRunTrace:
    safe_steps: list[SafeStepTrace] = []
    for step in run.steps:
        results_by_call_id = {
            str(result.get("tool_call_id")): result for result in step.tool_results
        }
        tools: list[SafeToolTrace] = []
        raw_calls = step.response.get("tool_calls", []) if step.response else []
        for raw_call in raw_calls:
            call = ToolCall.model_validate(raw_call)
            raw_result = results_by_call_id.get(call.id)
            output = raw_result.get("output") if raw_result else None
            error = raw_result.get("error") if raw_result else None
            tools.append(
                SafeToolTrace(
                    name=call.name,
                    arguments=redact(call.arguments),
                    result=(redact(output) if isinstance(output, dict) else None),
                    error=(redact(error) if isinstance(error, dict) else None),
                )
            )
        safe_steps.append(
            SafeStepTrace(
                step_number=step.step_number,
                duration_ms=step.duration_ms,
                input_tokens=step.input_tokens,
                output_tokens=step.output_tokens,
                error=step.error,
                tools=tools,
            )
        )
    return SafeRunTrace(
        run_id=run.id,
        status=run.status,
        provider=run.provider_name,
        model=run.model_name,
        prompt_version=run.prompt_version,
        steps=safe_steps,
    )
