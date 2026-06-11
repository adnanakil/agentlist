"""Per-silo Resy accounts (encrypted tokens).

Revision ID: 018
Revises: 017
Create Date: 2026-06-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index("ix_hal_resy_accounts_phone", table_name="hal_resy_accounts")
    op.drop_table("hal_resy_accounts")
