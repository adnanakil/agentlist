"""Notify-when-condition watchers (WATCH_FEATURE_SPEC.md).

A watch is persistent state (this row) + one shared background checker that
re-polls `condition` on a cheap model; the first time it's true it delivers
`notify` once and deactivates. Silent until then. Distinct from hal_cron_jobs
(clock schedule) and hal_reminders (static text).

Revision ID: 024
Revises: 023
Create Date: 2026-06-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_watches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(255), nullable=False),
        sa.Column("condition", sa.Text, nullable=False),
        sa.Column("check_prompt", sa.Text, nullable=False),
        sa.Column("notify", sa.Text, nullable=False),
        sa.Column("is_group", sa.Boolean, server_default=sa.false()),
        sa.Column("chat_id", sa.String(255), nullable=True),
        sa.Column("sender_phone", sa.String(255), nullable=True),
        sa.Column("poll_every_seconds", sa.Integer, nullable=False, server_default="150"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_polls", sa.Integer, nullable=False, server_default="60"),
        sa.Column("polls_done", sa.Integer, nullable=False, server_default="0"),
        sa.Column("consecutive_fails", sa.Integer, nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observation", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hal_watches_due", "hal_watches", ["active", "next_run_at"])


def downgrade() -> None:
    op.drop_index("ix_hal_watches_due", table_name="hal_watches")
    op.drop_table("hal_watches")
