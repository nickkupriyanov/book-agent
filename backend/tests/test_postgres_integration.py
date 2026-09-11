import os
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import get_db
from app.dependencies import get_llm_provider
from app.llm.fake import FakeLLMProvider
from app.llm.models import ModelResponse
from app.main import app
from app.seed import seed_database
from app.tools.models import ToolCall

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
DUNE_ID = "10000000-0000-0000-0000-000000000001"


def _alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


@pytest.fixture
def postgres_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[str, None, None]:
    raw_admin_url = os.getenv("TEST_POSTGRES_ADMIN_URL")
    if raw_admin_url is None:
        pytest.skip("set TEST_POSTGRES_ADMIN_URL to run PostgreSQL integration tests")

    admin_url = make_url(raw_admin_url)
    if admin_url.get_backend_name() != "postgresql":
        pytest.fail("TEST_POSTGRES_ADMIN_URL must use the PostgreSQL dialect")

    database_name = f"book_agent_test_{uuid4().hex}"
    admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')

    database_url = admin_url.set(database=database_name).render_as_string(
        hide_password=False
    )
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        yield database_url
    finally:
        get_settings.cache_clear()
        with admin_engine.connect() as connection:
            connection.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.exec_driver_sql(f'DROP DATABASE "{database_name}"')
        admin_engine.dispose()


@pytest.mark.postgres
def test_postgres_migrations_seed_crud_and_approval(
    postgres_database_url: str,
) -> None:
    config = _alembic_config()
    command.upgrade(config, "head")
    command.check(config)

    engine = sa.create_engine(postgres_database_url)
    inspector = sa.inspect(engine)
    assert {
        "books",
        "library_entries",
        "agent_runs",
        "agent_steps",
        "pending_actions",
    } <= set(inspector.get_table_names())
    assert "uq_pending_actions_active_run" in {
        index["name"] for index in inspector.get_indexes("pending_actions")
    }

    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    with testing_session() as session:
        assert seed_database(session) == 10
        assert seed_database(session) == 0

    provider = FakeLLMProvider(
        [
            ModelResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="postgres-remove-1",
                        name="remove_book",
                        arguments={"book_id": DUNE_ID},
                    )
                ],
            ),
            ModelResponse(text="Операция завершена."),
        ]
    )

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider] = lambda: provider
    try:
        with TestClient(app) as client:
            payload = {"book_id": DUNE_ID, "status": "reading"}
            assert client.post("/api/library", json=payload).status_code == 201
            assert client.post("/api/library", json=payload).status_code == 409

            waiting = client.post(
                "/api/agent/runs",
                json={"message": "Удали Дюну"},
            ).json()
            approve_url = (
                f"/api/agent/runs/{waiting['id']}/actions/"
                f"{waiting['pending_action']['id']}/approve"
            )
            approved = client.post(approve_url, json={})
            assert approved.status_code == 200
            assert approved.json()["replayed"] is False
            assert approved.json()["run"]["status"] == "completed"
            assert client.get("/api/library").json() == []

            replayed = client.post(approve_url, json={})
            assert replayed.status_code == 200
            assert replayed.json()["replayed"] is True
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
