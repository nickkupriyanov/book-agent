"""Create books and library entries.

Revision ID: 20260713_01
Revises:
Create Date: 2026-07-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260713_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "books",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_books_title", "books", ["title"], unique=False)

    op.create_table(
        "library_entries",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "want_to_read",
                "reading",
                "finished",
                name="reading_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "book_id"),
        sa.UniqueConstraint("user_id", "book_id", name="uq_library_user_book"),
    )


def downgrade() -> None:
    op.drop_table("library_entries")
    op.drop_index("ix_books_title", table_name="books")
    op.drop_table("books")
