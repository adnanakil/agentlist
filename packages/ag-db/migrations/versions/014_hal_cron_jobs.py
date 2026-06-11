"""Agentic cron jobs — scheduled full agent turns (not static reminders).

Revision ID: 014
Revises: 013
Create Date: 2026-06-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_cron_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(255), nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("recurrence", sa.String(16), nullable=False, server_default="once"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_group", sa.Boolean, server_default=sa.false()),
        sa.Column("chat_id", sa.String(255), nullable=True),
        sa.Column("sender_phone", sa.String(255), nullable=True),
        sa.Column("active", sa.Boolean, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_hal_cron_jobs_due", "hal_cron_jobs", ["active", "next_run_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_hal_cron_jobs_due", table_name="hal_cron_jobs")
    op.drop_table("hal_cron_jobs")
