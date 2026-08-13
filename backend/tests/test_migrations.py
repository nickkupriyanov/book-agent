from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from pytest import MonkeyPatch

from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
PREVIOUS_REVISION = "20260803_04"
HEAD_REVISION = "20260812_07"

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
BOOK_ID = UUID("10000000-0000-0000-0000-000000000001")
RUN_ID = UUID("20000000-0000-0000-0000-000000000001")
STEP_ID = UUID("30000000-0000-0000-0000-000000000001")


def upgrade_database(
    monkeypatch: MonkeyPatch,
    database_url: str,
    revision: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    command.upgrade(config, revision)
    get_settings.cache_clear()


def check_database(monkeypatch: MonkeyPatch, database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    command.check(config)
    get_settings.cache_clear()


def test_clean_database_upgrades_to_pending_actions_head(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'clean.db'}"

    upgrade_database(monkeypatch, database_url, "head")

    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    try:
        assert "pending_actions" in inspector.get_table_names()
        assert "version" in {
            column["name"] for column in inspector.get_columns("agent_runs")
        }
        assert next(
            column["type"].length
            for column in inspector.get_columns("agent_runs")
            if column["name"] == "status"
        ) == len("waiting_for_approval")
        assert "uq_pending_actions_active_run" in {
            index["name"] for index in inspector.get_indexes("pending_actions")
        }
        assert "result" in {
            column["name"]
            for column in inspector.get_columns("pending_actions")
        }
        with engine.connect() as connection:
            assert connection.scalar(
                sa.text("SELECT version_num FROM alembic_version")
            ) == HEAD_REVISION
        check_database(monkeypatch, database_url)
    finally:
        engine.dispose()


def test_upgrade_preserves_existing_books_library_and_agent_trace(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    upgrade_database(monkeypatch, database_url, PREVIOUS_REVISION)
    engine = sa.create_engine(database_url)
    now = datetime.now(timezone.utc)
    books = sa.table(
        "books",
        sa.column("id", sa.Uuid()),
        sa.column("title", sa.String()),
        sa.column("author", sa.String()),
        sa.column("tags", sa.JSON()),
    )
    library_entries = sa.table(
        "library_entries",
        sa.column("user_id", sa.Uuid()),
        sa.column("book_id", sa.Uuid()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    agent_runs = sa.table(
        "agent_runs",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("status", sa.String()),
        sa.column("user_message", sa.Text()),
        sa.column("working_state", sa.JSON()),
        sa.column("final_answer", sa.Text()),
        sa.column("stop_reason", sa.String()),
        sa.column("error", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    agent_steps = sa.table(
        "agent_steps",
        sa.column("id", sa.Uuid()),
        sa.column("run_id", sa.Uuid()),
        sa.column("step_number", sa.Integer()),
        sa.column("messages", sa.JSON()),
        sa.column("response", sa.JSON()),
        sa.column("tool_results", sa.JSON()),
        sa.column("error", sa.Text()),
        sa.column("duration_ms", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    with engine.begin() as connection:
        connection.execute(
            books.insert().values(
                id=BOOK_ID,
                title="Дюна",
                author="Фрэнк Герберт",
                tags=["science_fiction"],
            )
        )
        connection.execute(
            library_entries.insert().values(
                user_id=USER_ID,
                book_id=BOOK_ID,
                status="reading",
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            agent_runs.insert().values(
                id=RUN_ID,
                user_id=USER_ID,
                status="completed",
                user_message="Найди Дюну",
                working_state={
                    "goal": "Найди Дюну",
                    "completed_actions": [],
                    "initial_step_budget": 5,
                    "remaining_step_budget": 4,
                },
                final_answer="Дюна найдена",
                stop_reason="final_response",
                error=None,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            agent_steps.insert().values(
                id=STEP_ID,
                run_id=RUN_ID,
                step_number=1,
                messages=[{"role": "user", "content": "Найди Дюну"}],
                response={"text": "Дюна найдена", "tool_calls": []},
                tool_results=[],
                error=None,
                duration_ms=12,
                created_at=now,
            )
        )
    engine.dispose()

    upgrade_database(monkeypatch, database_url, "head")

    upgraded_engine = sa.create_engine(database_url)
    try:
        with upgraded_engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT COUNT(*) FROM books")) == 1
            assert connection.scalar(
                sa.text("SELECT COUNT(*) FROM library_entries")
            ) == 1
            assert connection.scalar(
                sa.text("SELECT COUNT(*) FROM agent_steps")
            ) == 1
            assert connection.execute(
                sa.text(
                    "SELECT user_message, final_answer, version FROM agent_runs"
                )
            ).one() == ("Найди Дюну", "Дюна найдена", 0)
            assert connection.scalar(
                sa.text("SELECT version_num FROM alembic_version")
            ) == HEAD_REVISION
    finally:
        upgraded_engine.dispose()


def test_status_upgrade_preserves_waiting_run(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'waiting.db'}"
    upgrade_database(monkeypatch, database_url, "20260811_06")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    agent_runs = sa.Table("agent_runs", metadata, autoload_with=engine)
    now = datetime.now(timezone.utc)
    waiting_run_id = UUID("20000000-0000-0000-0000-000000000002")
    with engine.begin() as connection:
        connection.execute(
            agent_runs.insert().values(
                id=waiting_run_id.hex,
                user_id=USER_ID.hex,
                status="waiting_for_approval",
                version=1,
                user_message="Удали Дюну",
                working_state={
                    "goal": "Удали Дюну",
                    "completed_actions": [],
                    "initial_step_budget": 5,
                    "remaining_step_budget": 4,
                },
                final_answer=None,
                stop_reason=None,
                error=None,
                created_at=now,
                updated_at=now,
            )
        )
    engine.dispose()

    upgrade_database(monkeypatch, database_url, "head")

    upgraded_engine = sa.create_engine(database_url)
    try:
        with upgraded_engine.connect() as connection:
            assert connection.execute(
                sa.text(
                    "SELECT status, version FROM agent_runs WHERE id = :run_id"
                ),
                {"run_id": waiting_run_id.hex},
            ).one() == ("waiting_for_approval", 1)
    finally:
        upgraded_engine.dispose()
