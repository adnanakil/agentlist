"""Add hal_user_skills + hal_curator_state tables.

Revision ID: 008
Revises: 007
Create Date: 2026-05-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_user_skills",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("keywords", JSONB, nullable=False, server_default="[]"),
        sa.Column("inputs", JSONB, nullable=False, server_default="[]"),
        sa.Column("files", JSONB, nullable=False, server_default="{}"),
        sa.Column("archived", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("archived_reason", sa.Text, nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hal_user_skills_name", "hal_user_skills", ["name"])

    op.create_table(
        "hal_curator_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_summary", sa.Text, nullable=False, server_default=""),
        sa.Column("last_actions_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_applied_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("paused", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("hal_curator_state")
    op.drop_index("ix_hal_user_skills_name", table_name="hal_user_skills")
    op.drop_table("hal_user_skills")
