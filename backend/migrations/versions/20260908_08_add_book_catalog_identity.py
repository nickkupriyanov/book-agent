"""Add external catalog identity to books.

Revision ID: 20260908_08
Revises: 20260812_07
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_08"
down_revision: str | None = "20260812_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("books") as batch_op:
        batch_op.add_column(
            sa.Column(
                "catalog_source",
                sa.String(length=32),
                server_default=sa.text("'local'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("external_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(sa.Column("isbn", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("cover_url", sa.String(length=512), nullable=True)
        )
        batch_op.add_column(
            sa.Column("catalog_updated_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_books_catalog_external_id",
            ["catalog_source", "external_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("books") as batch_op:
        batch_op.drop_constraint("uq_books_catalog_external_id", type_="unique")
        batch_op.drop_column("catalog_updated_at")
        batch_op.drop_column("cover_url")
        batch_op.drop_column("isbn")
        batch_op.drop_column("external_id")
        batch_op.drop_column("catalog_source")
