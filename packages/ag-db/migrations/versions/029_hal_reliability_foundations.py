"""HAL reliability foundations.

Adds bridge idempotency, durable outbound delivery, optimistic conversation
versions, action confirmations, and quarantined global-learning candidates.

Revision ID: 029
Revises: 028
Create Date: 2026-07-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hal_conversations",
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "hal_inbound_events",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("silo", sa.String(255), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="processing"),
        sa.Column("response", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_hal_inbound_events_silo_created",
        "hal_inbound_events",
        ["silo", "created_at"],
    )
    op.create_index(
        "ix_hal_inbound_events_status_updated",
        "hal_inbound_events",
        ["status", "updated_at"],
    )

    op.create_table(
        "hal_outbox_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("destination", sa.String(255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=True, unique=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_hal_outbox_pending", "hal_outbox_messages", ["status", "available_at"]
    )
    op.create_index("ix_hal_outbox_lease", "hal_outbox_messages", ["lease_until"])

    op.create_table(
        "hal_action_confirmations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("silo", sa.String(255), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("arguments_hash", sa.String(64), nullable=False),
        sa.Column("source_message_id", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_hal_action_confirmations_silo",
        "hal_action_confirmations",
        ["silo", "expires_at"],
    )

    op.create_table(
        "hal_learning_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("source_reflection_id", UUID(as_uuid=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_hal_learning_candidates_status",
        "hal_learning_candidates",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("hal_learning_candidates")
    op.drop_table("hal_action_confirmations")
    op.drop_table("hal_outbox_messages")
    op.drop_table("hal_inbound_events")
    op.drop_column("hal_conversations", "version")
