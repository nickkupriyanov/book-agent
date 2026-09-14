"""Add provider, prompt, and usage metadata to agent traces.

Revision ID: 20260914_11
Revises: 20260914_10
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_11"
down_revision: str | None = "20260914_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "provider_name",
                sa.String(length=64),
                server_default=sa.text("'unknown'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "model_name",
                sa.String(length=128),
                server_default=sa.text("'unknown'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "prompt_version",
                sa.String(length=64),
                server_default=sa.text("'unversioned'"),
                nullable=False,
            )
        )
    with op.batch_alter_table("agent_steps") as batch_op:
        batch_op.add_column(sa.Column("input_tokens", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("output_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_steps") as batch_op:
        batch_op.drop_column("output_tokens")
        batch_op.drop_column("input_tokens")
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_column("prompt_version")
        batch_op.drop_column("model_name")
        batch_op.drop_column("provider_name")
