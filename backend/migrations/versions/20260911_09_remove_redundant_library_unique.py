"""Remove redundant library entry uniqueness.

Revision ID: 20260911_09
Revises: 20260908_08
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_09"
down_revision: str | None = "20260908_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

constraint_name = "uq_library_user_book"


def _unique_constraint_exists() -> bool:
    inspector = sa.inspect(op.get_bind())
    return constraint_name in {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("library_entries")
    }


def upgrade() -> None:
    if _unique_constraint_exists():
        with op.batch_alter_table("library_entries") as batch_op:
            batch_op.drop_constraint(constraint_name, type_="unique")


def downgrade() -> None:
    if not _unique_constraint_exists():
        with op.batch_alter_table("library_entries") as batch_op:
            batch_op.create_unique_constraint(
                constraint_name,
                ["user_id", "book_id"],
            )
