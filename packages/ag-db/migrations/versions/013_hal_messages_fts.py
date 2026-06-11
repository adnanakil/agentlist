"""Append-only message archive + FTS for cross-session/temporal recall.

hal_conversations.history is a trimmed rolling window; this table keeps every
text turn durably and indexes it for Postgres full-text search so HAL can answer
"what did we talk about last Tuesday / about X" beyond the recent window.

Revision ID: 013
Revises: 012
Create Date: 2026-06-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_hal_messages_phone_created", "hal_messages", ["phone", "created_at"]
    )
    # Functional GIN index for full-text search over content.
    op.execute(
        "CREATE INDEX ix_hal_messages_fts ON hal_messages "
        "USING gin (to_tsvector('english', content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_hal_messages_fts")
    op.drop_index("ix_hal_messages_phone_created", table_name="hal_messages")
    op.drop_table("hal_messages")
