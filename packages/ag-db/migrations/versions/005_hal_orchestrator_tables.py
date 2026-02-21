"""Add HAL orchestrator tables (conversations, profiles, memories, reminders).

Revision ID: 005
Revises: 004
Create Date: 2026-02-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- hal_conversations --
    op.create_table(
        "hal_conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(20), unique=True, nullable=False),
        sa.Column("history", JSONB, nullable=False, server_default="[]"),
        sa.Column("message_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_hal_conversations_phone", "hal_conversations", ["phone"])

    # -- hal_user_profiles --
    op.create_table(
        "hal_user_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(20), unique=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("onboarded", sa.Boolean, server_default="false"),
        sa.Column("google_connected", sa.Boolean, server_default="false"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("extra_data", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_hal_user_profiles_phone", "hal_user_profiles", ["phone"])

    # -- hal_user_memories --
    op.create_table(
        "hal_user_memories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_hal_user_memories_phone", "hal_user_memories", ["phone"])

    # -- hal_reminders --
    op.create_table(
        "hal_reminders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recurrence", sa.String(20), nullable=True),
        sa.Column("sent", sa.Boolean, server_default="false"),
        sa.Column("sender_phone", sa.String(20), nullable=True),
        sa.Column("is_group", sa.Boolean, server_default="false"),
        sa.Column("group_name", sa.String(200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_hal_reminders_phone", "hal_reminders", ["phone"])
    op.create_index("ix_hal_reminders_due_at", "hal_reminders", ["due_at"])


def downgrade() -> None:
    op.drop_index("ix_hal_reminders_due_at", table_name="hal_reminders")
    op.drop_index("ix_hal_reminders_phone", table_name="hal_reminders")
    op.drop_table("hal_reminders")

    op.drop_index("ix_hal_user_memories_phone", table_name="hal_user_memories")
    op.drop_table("hal_user_memories")

    op.drop_index("ix_hal_user_profiles_phone", table_name="hal_user_profiles")
    op.drop_table("hal_user_profiles")

    op.drop_index("ix_hal_conversations_phone", table_name="hal_conversations")
    op.drop_table("hal_conversations")
