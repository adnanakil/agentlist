"""Skill trajectories — captured multi-tool tasks for auto-skill distillation.

Revision ID: 015
Revises: 014
Create Date: 2026-06-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_skill_trajectories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(255), nullable=False),
        sa.Column("goal", sa.Text, nullable=False),
        sa.Column("steps", JSONB, nullable=False, server_default="[]"),
        sa.Column("outcome", sa.Text, nullable=False, server_default=""),
        sa.Column("processed", sa.Boolean, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_hal_skill_trajectories_processed", "hal_skill_trajectories", ["processed"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hal_skill_trajectories_processed", table_name="hal_skill_trajectories"
    )
    op.drop_table("hal_skill_trajectories")
