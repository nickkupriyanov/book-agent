import json
from collections.abc import Generator
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db import get_db
from app.dependencies import get_llm_provider
from app.llm.fake import FakeLLMProvider
from app.llm.models import ModelResponse
from app.main import app
from app.models import Base
from app.seed import seed_database
from app.tools.models import ToolCall

DUNE_ID = "10000000-0000-0000-0000-000000000001"


def _scripted_provider() -> FakeLLMProvider:
    return FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="demo-read-1",
                        name="get_user_library",
                        arguments={},
                    )
                ],
            ),
            ModelResponse(text="Библиотека пока пуста."),
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="demo-search-1",
                        name="search_books",
                        arguments={"query": "Дюна", "limit": 5},
                    )
                ],
            ),
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="demo-add-1",
                        name="add_book",
                        arguments={"book_id": DUNE_ID, "status": "reading"},
                    )
                ],
            ),
            ModelResponse(text="Дюна добавлена в статусе «читаю»."),
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="demo-remove-1",
                        name="remove_book",
                        arguments={"book_id": DUNE_ID},
                    )
                ],
            ),
            ModelResponse(text="Дюна удалена из библиотеки."),
        ]
    )


def _post_run(client: TestClient, message: str) -> dict[str, Any]:
    response = client.post("/api/agent/runs", json={"message": message})
    response.raise_for_status()
    return response.json()


def _tool_names(run: dict[str, Any]) -> list[str]:
    return [
        result["tool_name"]
        for step in run["steps"]
        for result in step["tool_results"]
    ]


def run_demo() -> dict[str, Any]:
    with TemporaryDirectory(prefix="book-agent-demo-") as directory:
        engine = create_engine(
            f"sqlite:///{directory}/demo.db",
            connect_args={"check_same_thread": False},
        )
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        Base.metadata.create_all(engine)
        with session_factory() as session:
            seed_database(session)

        def override_get_db() -> Generator[Session, None, None]:
            with session_factory() as session:
                yield session

        provider = _scripted_provider()
        settings = Settings(catalog_provider="local")
        previous_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_llm_provider] = lambda: provider
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            with TestClient(app) as client:
                read_run = _post_run(client, "Что сейчас в моей библиотеке?")
                write_run = _post_run(client, "Найди Дюну и добавь её в читаю")
                library_before_approval = client.get("/api/library").json()
                removal = _post_run(client, "Удали Дюну из библиотеки")
                action = removal["pending_action"]
                approval_response = client.post(
                    f"/api/agent/runs/{removal['id']}/actions/{action['id']}/approve",
                    json={},
                )
                approval_response.raise_for_status()
                approved_run = approval_response.json()["run"]
                library_after_approval = client.get("/api/library").json()
                traces = []
                for run in (read_run, write_run, approved_run):
                    trace_response = client.get(
                        f"/api/agent/runs/{run['id']}/trace"
                    )
                    trace_response.raise_for_status()
                    traces.append(trace_response.json())
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous_overrides)
            Base.metadata.drop_all(engine)
            engine.dispose()

    assert len(library_before_approval) == 1
    assert library_after_approval == []
    return {
        "read": {
            "status": read_run["status"],
            "tools": _tool_names(read_run),
        },
        "multi_step_write": {
            "status": write_run["status"],
            "tools": _tool_names(write_run),
        },
        "approval": {
            "proposed_status": removal["status"],
            "completed_status": approved_run["status"],
            "book_count_before": len(library_before_approval),
            "book_count_after": len(library_after_approval),
        },
        "safe_traces": [
            {
                "status": trace["status"],
                "tools": [
                    tool["name"]
                    for step in trace["steps"]
                    for tool in step["tools"]
                ],
            }
            for trace in traces
        ],
    }


def main() -> None:
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
