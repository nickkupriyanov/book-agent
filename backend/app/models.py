from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ReadingStatus(str, Enum):
    WANT_TO_READ = "want_to_read"
    READING = "reading"
    FINISHED = "finished"


class Book(Base):
    __tablename__ = "books"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    author: Mapped[str] = mapped_column(String(255))


class LibraryEntry(Base):
    __tablename__ = "library_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id", name="uq_library_user_book"),
    )

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
