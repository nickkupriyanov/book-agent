from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ReadingStatus(str, Enum):
    WANT_TO_READ = "want_to_read"
    READING = "reading"
    FINISHED = "finished"


class AgentRunStatus(str, Enum):
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    STEP_LIMIT_EXCEEDED = "step_limit_exceeded"


class PendingActionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        UniqueConstraint(
            "catalog_source",
            "external_id",
            name="uq_books_catalog_external_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    author: Mapped[str] = mapped_column(String(255))
    tags: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        server_default=text("'[]'"),
    )
    catalog_source: Mapped[str] = mapped_column(
        String(32),
        default="local",
        server_default=text("'local'"),
    )
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    isbn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    catalog_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class LibraryEntry(Base):
    __tablename__ = "library_entries"

    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    book_id: Mapped[UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[ReadingStatus] = mapped_column(
        SqlEnum(
            ReadingStatus,
            name="reading_status",
            native_enum=False,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    book: Mapped[Book] = relationship(lazy="joined")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(index=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        SqlEnum(
            AgentRunStatus,
            name="agent_run_status",
            native_enum=False,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        default=AgentRunStatus.RUNNING,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
    )
    user_message: Mapped[str] = mapped_column(Text)
    working_state: Mapped[dict[str, object]] = mapped_column(JSON)
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentStep.step_number",
        lazy="selectin",
    )
    pending_actions: Mapped[list["PendingAction"]] = relationship(
        cascade="all, delete-orphan",
        order_by="PendingAction.created_at",
        lazy="selectin",
    )

    @property
    def pending_action(self) -> "PendingAction | None":
        return next(
            (
                action
                for action in reversed(self.pending_actions)
                if action.status is PendingActionStatus.PENDING
            ),
            None,
        )


class PendingAction(Base):
    __tablename__ = "pending_actions"
    __table_args__ = (
        Index(
            "uq_pending_actions_active_run",
            "run_id",
            unique=True,
            sqlite_where=text("status = 'pending'"),
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(index=True)
    tool_call_id: Mapped[str] = mapped_column(String(255))
    tool_name: Mapped[str] = mapped_column(String(255))
    arguments: Mapped[dict[str, object]] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[PendingActionStatus] = mapped_column(
        SqlEnum(
            PendingActionStatus,
            name="pending_action_status",
            native_enum=False,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        default=PendingActionStatus.PENDING,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    expected_run_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "step_number",
            name="uq_agent_step_run_number",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        index=True,
    )
    step_number: Mapped[int] = mapped_column(Integer)
    messages: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    response: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    tool_results: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        default=list,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    run: Mapped[AgentRun] = relationship(back_populates="steps")
