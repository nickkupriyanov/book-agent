from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_llm_provider
from app.llm.fake import FakeLLMProvider
from app.llm.models import ModelResponse
from app.main import app
from app.models import Book, LibraryEntry, ReadingStatus
from app.repository import BookRepository
from app.service import BookService
from app.tools.models import ToolCall

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")
NINETEEN_EIGHTY_FOUR_ID = UUID("10000000-0000-0000-0000-000000000002")
MARTIAN_ID = UUID("10000000-0000-0000-0000-000000000003")
ATOMIC_HABITS_ID = UUID("10000000-0000-0000-0000-000000000004")
SOLARIS_ID = UUID("10000000-0000-0000-0000-000000000005")
ROADSIDE_PICNIC_ID = UUID("10000000-0000-0000-0000-000000000006")
FLOWERS_FOR_ALGERNON_ID = UUID("10000000-0000-0000-0000-000000000007")
LEFT_HAND_OF_DARKNESS_ID = UUID("10000000-0000-0000-0000-000000000008")
SAPIENS_ID = UUID("10000000-0000-0000-0000-000000000010")


def run_agent(
    client: TestClient,
    *,
    message: str,
    responses: list[ModelResponse],
) -> tuple[dict[str, object], FakeLLMProvider]:
    provider = FakeLLMProvider(responses)
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.post("/api/agent/runs", json={"message": message})

    assert response.status_code == 201
    return response.json(), provider


def successful_tool_outputs(
    payload: dict[str, object],
    tool_name: str,
) -> list[dict[str, object]]:
    return [
        result["output"]
        for step in payload["steps"]
        for result in step["tool_results"]
        if result["tool_name"] == tool_name and result["error"] is None
    ]


def called_tool_names(payload: dict[str, object]) -> list[str]:
    return [
        call["name"]
        for step in payload["steps"]
        for call in step["response"]["tool_calls"]
    ]


def test_recommendation_scenario_returns_three_valid_new_ids(
    client: TestClient,
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    dune = service.add_book(USER_ID, DUNE_ID, ReadingStatus.FINISHED)
    nineteen_eighty_four = service.add_book(
        USER_ID,
        NINETEEN_EIGHTY_FOUR_ID,
        ReadingStatus.FINISHED,
    )
    service.add_book(
        USER_ID,
        ATOMIC_HABITS_ID,
        ReadingStatus.READING,
    )
    dune.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    nineteen_eighty_four.updated_at = datetime(
        2026,
        1,
        2,
        tzinfo=timezone.utc,
    )
    session.commit()

    payload, provider = run_agent(
        client,
        message=(
            "Посмотри, что я недавно прочитал, и предложи три похожие книги, "
            "которых ещё нет в моей библиотеке"
        ),
        responses=[
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="library-1",
                        name="get_user_library",
                        arguments={
                            "status": "finished",
                            "recent_first": True,
                            "limit": 3,
                        },
                    )
                ],
            ),
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="recommend-1",
                        name="find_similar_books",
                        arguments={
                            "source_book_ids": [
                                str(NINETEEN_EIGHTY_FOUR_ID),
                                str(DUNE_ID),
                            ],
                            "limit": 3,
                        },
                    )
                ],
            ),
            ModelResponse(
                text=(
                    "Рекомендую «Пикник на обочине», «Цветы для Элджернона» "
                    "и «Левую руку Тьмы»."
                )
            ),
        ],
    )

    assert payload["status"] == "completed"
    assert payload["final_answer"]
    assert called_tool_names(payload) == [
        "get_user_library",
        "find_similar_books",
    ]
    library_output = successful_tool_outputs(
        payload,
        "get_user_library",
    )[0]
    assert [entry["book"]["id"] for entry in library_output["entries"]] == [
        str(NINETEEN_EIGHTY_FOUR_ID),
        str(DUNE_ID),
    ]

    recommendation_output = successful_tool_outputs(
        payload,
        "find_similar_books",
    )[0]
    recommendations = recommendation_output["recommendations"]
    recommendation_ids = [item["book"]["id"] for item in recommendations]
    catalog_ids = {str(book_id) for book_id in session.scalars(select(Book.id))}
    library_ids = {
        str(book_id)
        for book_id in session.scalars(
            select(LibraryEntry.book_id).where(
                LibraryEntry.user_id == USER_ID
            )
        )
    }

    assert recommendation_ids == [
        str(ROADSIDE_PICNIC_ID),
        str(FLOWERS_FOR_ALGERNON_ID),
        str(LEFT_HAND_OF_DARKNESS_ID),
    ]
    assert len(recommendation_ids) == len(set(recommendation_ids)) == 3
    assert set(recommendation_ids) <= catalog_ids
    assert set(recommendation_ids).isdisjoint(library_ids)
    assert all(item["score"] > 0 for item in recommendations)
    assert all(item["matched_tags"] for item in recommendations)

    completed_actions = payload["working_state"]["completed_actions"]
    assert [action["tool_name"] for action in completed_actions] == [
        "get_user_library",
        "find_similar_books",
    ]
    assert [action["tool_call_id"] for action in completed_actions] == [
        "library-1",
        "recommend-1",
    ]
    assert len(payload["steps"]) == len(provider.calls) == 3


def test_recommendation_scenario_excludes_an_added_candidate(
    client: TestClient,
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    service.add_book(USER_ID, DUNE_ID, ReadingStatus.FINISHED)
    service.add_book(
        USER_ID,
        LEFT_HAND_OF_DARKNESS_ID,
        ReadingStatus.WANT_TO_READ,
    )

    payload, _ = run_agent(
        client,
        message="Предложи ещё три книги, похожие на недавно прочитанные",
        responses=[
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="library-repeat",
                        name="get_user_library",
                        arguments={
                            "status": "finished",
                            "recent_first": True,
                            "limit": 3,
                        },
                    )
                ],
            ),
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="recommend-repeat",
                        name="find_similar_books",
                        arguments={
                            "source_book_ids": [str(DUNE_ID)],
                            "limit": 3,
                        },
                    )
                ],
            ),
            ModelResponse(text="Нашёл ещё три варианта."),
        ],
    )

    recommendations = successful_tool_outputs(
        payload,
        "find_similar_books",
    )[0]["recommendations"]
    recommendation_ids = [item["book"]["id"] for item in recommendations]

    assert recommendation_ids == [
        str(NINETEEN_EIGHTY_FOUR_ID),
        str(MARTIAN_ID),
        str(SOLARIS_ID),
    ]
    assert str(LEFT_HAND_OF_DARKNESS_ID) not in recommendation_ids


def test_recommendation_scenario_returns_fewer_without_inventing_ids(
    client: TestClient,
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    service.add_book(USER_ID, ATOMIC_HABITS_ID, ReadingStatus.FINISHED)
    service.add_book(
        USER_ID,
        FLOWERS_FOR_ALGERNON_ID,
        ReadingStatus.WANT_TO_READ,
    )

    payload, _ = run_agent(
        client,
        message="Предложи три похожие книги",
        responses=[
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="library-short",
                        name="get_user_library",
                        arguments={
                            "status": "finished",
                            "recent_first": True,
                            "limit": 3,
                        },
                    )
                ],
            ),
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="recommend-short",
                        name="find_similar_books",
                        arguments={
                            "source_book_ids": [str(ATOMIC_HABITS_ID)],
                            "limit": 3,
                        },
                    )
                ],
            ),
            ModelResponse(text="Нашёл только один подходящий вариант."),
        ],
    )

    recommendations = successful_tool_outputs(
        payload,
        "find_similar_books",
    )[0]["recommendations"]

    assert [item["book"]["id"] for item in recommendations] == [
        str(SAPIENS_ID)
    ]
    assert payload["final_answer"]


def test_agent_api_lists_current_books(
    client: TestClient,
    session: Session,
) -> None:
    BookService(BookRepository(session)).add_book(
        USER_ID,
        DUNE_ID,
        ReadingStatus.READING,
    )

    payload, _ = run_agent(
        client,
        message="Покажи книги, которые я сейчас читаю",
        responses=[
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="library-reading",
                        name="get_user_library",
                        arguments={"status": "reading"},
                    )
                ],
            ),
            ModelResponse(text="Сейчас вы читаете «Дюну»."),
        ],
    )

    entries = successful_tool_outputs(
        payload,
        "get_user_library",
    )[0]["entries"]
    assert [entry["book"]["id"] for entry in entries] == [str(DUNE_ID)]


def test_agent_api_updates_reading_status(
    client: TestClient,
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    service.add_book(
        USER_ID,
        NINETEEN_EIGHTY_FOUR_ID,
        ReadingStatus.READING,
    )

    payload, _ = run_agent(
        client,
        message="Я дочитал 1984. Отметь её как прочитанную",
        responses=[
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="search-finished",
                        name="search_books",
                        arguments={"query": "1984", "limit": 5},
                    )
                ],
            ),
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="update-finished",
                        name="update_book_status",
                        arguments={
                            "book_id": str(NINETEEN_EIGHTY_FOUR_ID),
                            "status": "finished",
                        },
                    )
                ],
            ),
            ModelResponse(text="Отметил «1984» как прочитанную."),
        ],
    )

    assert payload["status"] == "completed"
    assert called_tool_names(payload) == [
        "search_books",
        "update_book_status",
    ]
    entries = service.get_library(USER_ID)
    assert len(entries) == 1
    assert entries[0].status is ReadingStatus.FINISHED
