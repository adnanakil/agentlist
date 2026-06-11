"""Ambient watched groups (trip-independent).

A group in hal_watched_groups gets ALL its messages forwarded to HAL (like an
active trip does), but without any trip semantics — HAL just watches it and
stays quiet unless addressed or useful. This replaces the old hack of leaving a
stale trip 'active' to keep a group watched.

Revision ID: 011
Revises: 010
Create Date: 2026-06-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_watched_groups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("chat_id", sa.String(255), nullable=False, unique=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hal_watched_groups_chat_id", "hal_watched_groups", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_hal_watched_groups_chat_id", table_name="hal_watched_groups")
    op.drop_table("hal_watched_groups")
