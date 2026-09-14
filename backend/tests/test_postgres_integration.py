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

from app.catalog.models import CatalogSource
from app.catalog.open_library import OpenLibraryCatalog
from app.config import get_settings
from app.db import get_db
from app.dependencies import get_llm_provider
from app.llm.fake import FakeLLMProvider
from app.llm.models import ModelResponse
from app.main import app
from app.models import Book, ReadingStatus
from app.repository import BookRepository
from app.seed import seed_database
from app.service import BookService
from app.tools.models import ToolCall

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
DUNE_ID = "10000000-0000-0000-0000-000000000001"


class FixtureOpenLibraryTransport:
    def search(self, query: str, limit: int) -> object:
        return {
            "docs": [
                {
                    "key": "/works/OL45804W",
                    "title": "Fantastic Mr Fox",
                    "author_name": ["Roald Dahl"],
                    "isbn": ["9780140328721"],
                    "subject_key": ["Children's stories"],
                }
            ]
        }


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
        "user_notes",
        "note_chunks",
        "user_preferences",
    } <= set(inspector.get_table_names())
    assert "uq_pending_actions_active_run" in {
        index["name"] for index in inspector.get_indexes("pending_actions")
    }
    assert {"provider_name", "model_name", "prompt_version"} <= {
        column["name"] for column in inspector.get_columns("agent_runs")
    }
    assert {"input_tokens", "output_tokens"} <= {
        column["name"] for column in inspector.get_columns("agent_steps")
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


@pytest.mark.parametrize("database_backend", ["sqlite", "postgresql"])
def test_external_catalog_domain_contract_on_both_databases(
    database_backend: str,
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if database_backend == "postgresql":
        database_url = request.getfixturevalue("postgres_database_url")
    else:
        database_url = f"sqlite:///{tmp_path / 'stage8-contract.db'}"
        monkeypatch.setenv("DATABASE_URL", database_url)
        get_settings.cache_clear()

    command.upgrade(_alembic_config(), "head")
    engine = sa.create_engine(database_url)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with testing_session() as session:
            service = BookService(
                BookRepository(session),
                OpenLibraryCatalog(FixtureOpenLibraryTransport()),
            )

            first = service.search_catalog("Fantastic Mr Fox", 5)
            book_id = first.books[0].id
            service.add_book(
                user_id=get_settings().demo_user_id,
                book_id=book_id,
                status=ReadingStatus.WANT_TO_READ,
            )
            library = service.get_library(get_settings().demo_user_id)
            second = service.search_catalog("Fantastic Mr Fox", 5)

            assert first.source is CatalogSource.OPEN_LIBRARY
            assert second.books[0].id == book_id
            assert library[0].book_id == book_id
            assert session.scalar(
                sa.select(sa.func.count())
                .select_from(Book)
                .where(Book.id == book_id)
            ) == 1
    finally:
        engine.dispose()
        get_settings.cache_clear()
