"""Add agent working state.

Revision ID: 20260803_04
Revises: 20260727_03
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_04"
down_revision: str | None = "20260727_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("working_state", sa.JSON(), nullable=True),
    )

    connection = op.get_bind()
    agent_runs = sa.table(
        "agent_runs",
        sa.column("id", sa.Uuid()),
        sa.column("user_message", sa.Text()),
        sa.column("working_state", sa.JSON()),
    )
    agent_steps = sa.table(
        "agent_steps",
        sa.column("run_id", sa.Uuid()),
        sa.column("step_number", sa.Integer()),
        sa.column("tool_results", sa.JSON()),
    )

    for run_id, user_message in connection.execute(
        sa.select(agent_runs.c.id, agent_runs.c.user_message)
    ):
        steps = connection.execute(
            sa.select(
                agent_steps.c.step_number,
                agent_steps.c.tool_results,
            )
            .where(agent_steps.c.run_id == run_id)
            .order_by(agent_steps.c.step_number)
        )
        completed_actions = []
        step_count = 0
        for step_number, tool_results in steps:
            step_count += 1
            for result in tool_results or []:
                if (
                    result.get("error") is None
                    and result.get("output") is not None
                ):
                    completed_actions.append(
                        {
                            "step_number": step_number,
                            "tool_call_id": result["tool_call_id"],
                            "tool_name": result["tool_name"],
                        }
                    )

        initial_budget = max(step_count, 1)
        connection.execute(
            agent_runs.update()
            .where(agent_runs.c.id == run_id)
            .values(
                working_state={
                    "goal": user_message or "Legacy agent run",
                    "completed_actions": completed_actions,
                    "initial_step_budget": initial_budget,
                    "remaining_step_budget": 0,
                }
            )
        )

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.alter_column(
            "working_state",
            existing_type=sa.JSON(),
            nullable=False,
        )


def downgrade() -> None:
    op.drop_column("agent_runs", "working_state")
