"""Outbox channel routing for multi-transport bridges.

`channel` on hal_outbox_messages lets each bridge (iMessage Mac bridge,
WhatsApp bridge) drain only its own deliveries — without it, two pollers
steal each other's messages. `hal_silo_channels` records which transport a
silo last spoke on so producers that enqueue by silo alone (cron digests,
billing, first-win) route to the right bridge. server_default 'imessage'
keeps rows from not-yet-deployed producers drainable by the legacy bridge.

Revision ID: 031
Revises: 030
Create Date: 2026-07-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "031"
down_revision: Union[str, None] = "030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hal_outbox_messages",
        sa.Column(
            "channel", sa.String(16), nullable=False, server_default="imessage"
        ),
    )
    op.create_table(
        "hal_silo_channels",
        sa.Column("silo", sa.String(255), primary_key=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("hal_silo_channels")
    op.drop_column("hal_outbox_messages", "channel")
