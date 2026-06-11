"""Pending Resy bookings (propose→confirm state machine).

Revision ID: 019
Revises: 018
Create Date: 2026-06-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_resy_pending_bookings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(255), nullable=False),
        sa.Column("venue_id", sa.String(64), nullable=False),
        sa.Column("venue_name", sa.String(300), nullable=True),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("slot_time", sa.String(40), nullable=False),
        sa.Column("table_type", sa.String(80), nullable=True),
        sa.Column("party_size", sa.Integer, nullable=False),
        sa.Column("config_token", sa.Text, nullable=False),
        sa.Column("has_fee", sa.Boolean, server_default=sa.false()),
        sa.Column("fee_text", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("confirmation_number", sa.String(120), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hal_resy_pending_phone", "hal_resy_pending_bookings", ["phone", "status"])
    # At most one live proposal per silo.
    op.create_index(
        "uq_hal_resy_pending_live",
        "hal_resy_pending_bookings",
        ["phone"],
        unique=True,
        postgresql_where=sa.text("status = 'proposed'"),
    )


def downgrade() -> None:
    op.drop_index("uq_hal_resy_pending_live", table_name="hal_resy_pending_bookings")
    op.drop_index("ix_hal_resy_pending_phone", table_name="hal_resy_pending_bookings")
    op.drop_table("hal_resy_pending_bookings")
