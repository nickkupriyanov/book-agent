"""Align agent run status with approval states.

Revision ID: 20260812_07
Revises: 20260811_06
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_07"
down_revision: str | None = "20260811_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

old_status = sa.Enum(
    "running",
    "completed",
    "failed",
    "step_limit_exceeded",
    name="agent_run_status",
    native_enum=False,
)
new_status = sa.Enum(
    "running",
    "waiting_for_approval",
    "completed",
    "failed",
    "step_limit_exceeded",
    name="agent_run_status",
    native_enum=False,
)


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=old_status,
            type_=new_status,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=new_status,
            type_=old_status,
            existing_nullable=False,
        )
