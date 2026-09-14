from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.repository import AgentRunRepository
from app.agent.service import AgentService
from app.llm.exceptions import LLMTimeoutError
from app.llm.fake import FakeLLMProvider
from app.llm.models import ModelResponse, TokenUsage
from app.memory.repository import MemoryRepository
from app.memory.service import MemoryService
from app.models import AgentRun
from app.observability import REDACTED, build_safe_trace, redact
from app.tools.memory import SEARCH_USER_NOTES_TOOL, SearchUserNotesHandler
from app.tools.models import ToolCall
from app.tools.registry import ToolRegistry

USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_redaction_removes_secret_keys_values_and_note_content() -> None:
    payload = {
        "api_key": "plain-value",
        "nested": {
            "authorization": "Bearer private-token",
            "fragment": "private note",
            "input_tokens": 42,
            "url": "https://example.test/?key=sk-abcdefgh1234",
        },
    }

    assert redact(payload) == {
        "api_key": REDACTED,
        "nested": {
            "authorization": REDACTED,
            "fragment": REDACTED,
            "input_tokens": 42,
            "url": REDACTED,
        },
    }


def test_safe_trace_records_metadata_usage_and_redacts_note_fragment(
    session: Session,
) -> None:
    memory = MemoryService(MemoryRepository(session))
    memory.create_note(USER_ID, "Секретная экология")
    registry = ToolRegistry()
    registry.register(
        SEARCH_USER_NOTES_TOOL,
        SearchUserNotesHandler(memory, USER_ID),
    )
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="trace-note-1",
                        name="search_user_notes",
                        arguments={"query": "экология"},
                    )
                ],
                usage=TokenUsage(input_tokens=12, output_tokens=3),
            ),
            ModelResponse(text="Нашёл заметку."),
        ]
    )
    run = AgentService(
        provider,
        registry,
        AgentRunRepository(session),
        provider_name="fake",
        model_name="scripted",
    ).run(USER_ID, "Что я писал?")

    trace = build_safe_trace(run)
    serialized = trace.model_dump_json()

    assert trace.provider == "fake"
    assert trace.model == "scripted"
    assert trace.prompt_version == "book-agent-system-v1"
    assert trace.steps[0].input_tokens == 12
    assert trace.steps[0].output_tokens == 3
    assert trace.steps[0].tools[0].result["citations"][0]["fragment"] == REDACTED
    assert "Секретная экология" not in serialized
    assert "Что я писал?" not in serialized


def test_failed_run_also_has_safe_trace(session: Session) -> None:
    provider = Mock()
    provider.generate.side_effect = LLMTimeoutError("sk-private123456")
    repository = AgentRunRepository(session)
    agent = AgentService(
        provider,
        ToolRegistry(),
        repository,
        provider_name="deepseek",
        model_name="test-model",
    )

    with pytest.raises(LLMTimeoutError):
        agent.run(USER_ID, "Секретный запрос")

    run = session.scalar(select(AgentRun))
    assert run is not None
    restored = repository.get_run(run.id)
    assert restored is not None
    trace = build_safe_trace(restored)

    assert trace.status.value == "failed"
    assert trace.steps[0].error == "LLMTimeoutError"
    assert "private" not in trace.model_dump_json()
