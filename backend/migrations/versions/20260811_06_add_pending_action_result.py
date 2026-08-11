"""Add persisted pending action result.

Revision ID: 20260811_06
Revises: 20260810_05
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_06"
down_revision: str | None = "20260810_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pending_actions",
        sa.Column("result", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pending_actions", "result")
