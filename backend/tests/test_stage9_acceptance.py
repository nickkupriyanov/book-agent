from uuid import UUID

from sqlalchemy.orm import Session

from app.agent.repository import AgentRunRepository
from app.agent.service import AgentService
from app.llm.fake import FakeLLMProvider
from app.llm.models import ModelResponse
from app.memory.repository import MemoryRepository
from app.memory.service import MemoryService
from app.schemas import AgentRunResponse
from app.tools.memory import SEARCH_USER_NOTES_TOOL, SearchUserNotesHandler
from app.tools.models import ToolCall
from app.tools.registry import ToolRegistry

USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _memory_agent(
    session: Session,
    memory_service: MemoryService,
    provider: FakeLLMProvider,
) -> AgentService:
    registry = ToolRegistry()
    registry.register(
        SEARCH_USER_NOTES_TOOL,
        SearchUserNotesHandler(memory_service, USER_ID),
    )
    return AgentService(provider, registry, AgentRunRepository(session))


def test_agent_answers_about_personal_themes_with_real_note_citations(
    session: Session,
) -> None:
    memory_service = MemoryService(MemoryRepository(session))
    politics = memory_service.create_note(
        USER_ID,
        "Меня заинтересовала политика воды и экология пустыни.",
    )
    religion = memory_service.create_note(
        USER_ID,
        "Религия влияет на власть и общество.",
    )
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="stage9-notes-1",
                        name="search_user_notes",
                        arguments={
                            "query": "политика экология религия власть",
                            "limit": 5,
                        },
                    )
                ],
            ),
            ModelResponse(
                text=(
                    "Вас интересовали экология и политика "
                    f"(note:{politics.id}), а также религия и власть "
                    f"(note:{religion.id})."
                )
            ),
        ]
    )

    run = _memory_agent(session, memory_service, provider).run(
        USER_ID,
        "Какие темы интересовали меня в последних заметках?",
    )
    response = AgentRunResponse.model_validate(run)

    assert response.status.value == "completed"
    assert str(politics.id) in response.final_answer
    assert str(religion.id) in response.final_answer
    tool_output = response.steps[0].tool_results[0]["output"]
    assert {citation["note_id"] for citation in tool_output["citations"]} == {
        str(politics.id),
        str(religion.id),
    }
    assert [action.tool_name for action in response.working_state.completed_actions] == [
        "search_user_notes"
    ]


def test_agent_gets_explicit_empty_context_instead_of_fabricated_source(
    session: Session,
) -> None:
    memory_service = MemoryService(MemoryRepository(session))
    memory_service.create_note(USER_ID, "Политика и экология")
    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="stage9-empty-1",
                        name="search_user_notes",
                        arguments={"query": "музыка"},
                    )
                ],
            ),
            ModelResponse(
                text="В заметках нет контекста, подтверждающего эту тему."
            ),
        ]
    )

    run = _memory_agent(session, memory_service, provider).run(
        USER_ID,
        "Что я писал о музыке?",
    )

    assert run.status.value == "completed"
    assert run.steps[0].tool_results[0]["output"] == {"citations": []}
    assert "нет контекста" in run.final_answer
