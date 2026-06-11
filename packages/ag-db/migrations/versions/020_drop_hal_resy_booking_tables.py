"""Drop the Resy account/booking tables — descoped to find-and-link only.

HAL no longer books on anyone's behalf (no stored Resy accounts, no per-user
booking), so these (empty) tables from 018/019 are removed. Resy is now read-only
search/availability + a Resy deep link the user books with themselves.

Revision ID: 020
Revises: 019
Create Date: 2026-06-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("hal_resy_pending_bookings")
    op.drop_table("hal_resy_accounts")


def downgrade() -> None:
    op.create_table(
        "hal_resy_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(255), nullable=False, unique=True),
        sa.Column("resy_email", sa.String(320), nullable=True),
        sa.Column("auth_token_enc", sa.Text, nullable=False, server_default=""),
        sa.Column("refresh_token_enc", sa.Text, nullable=True),
        sa.Column("token_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_methods_enc", sa.Text, nullable=True),
        sa.Column("connection_status", sa.String(20), nullable=False, server_default="connected"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hal_resy_accounts_phone", "hal_resy_accounts", ["phone"])
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
