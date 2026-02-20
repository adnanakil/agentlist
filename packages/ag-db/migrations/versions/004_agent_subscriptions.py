"""Add agent_subscriptions table for HAL signup flow.

Revision ID: 004
Revises: 003
Create Date: 2026-02-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("agent_slug", sa.String(100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending_provision",
                "active",
                "suspended",
                "cancelled",
                name="subscription_status",
            ),
            nullable=False,
        ),
        sa.Column("provisioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("phone", "agent_slug", name="uq_subscription_phone_agent"),
    )
    op.create_index(
        "ix_agent_subscriptions_status", "agent_subscriptions", ["status"]
    )
    op.create_index(
        "ix_agent_subscriptions_phone", "agent_subscriptions", ["phone"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_subscriptions_phone", table_name="agent_subscriptions")
    op.drop_index("ix_agent_subscriptions_status", table_name="agent_subscriptions")
    op.drop_table("agent_subscriptions")
    op.execute("DROP TYPE IF EXISTS subscription_status")
