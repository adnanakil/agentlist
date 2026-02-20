"""Add consumer_credentials table and required_consumer_credentials column on agents.

Revision ID: 003
Revises: 002
Create Date: 2026-02-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # consumer_credentials table
    op.create_table(
        "consumer_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False
        ),
        sa.Column("service_name", sa.String(100), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary, nullable=False),
        sa.Column("encryption_key_id", sa.String(100), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "service_name", name="uq_consumer_credential"),
    )
    op.create_index(
        "ix_consumer_credentials_account", "consumer_credentials", ["account_id"]
    )

    # required_consumer_credentials on agents (JSONB list of credential names agents need from consumers)
    op.add_column(
        "agents",
        sa.Column("required_consumer_credentials", JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("agents", "required_consumer_credentials")
    op.drop_index("ix_consumer_credentials_account", table_name="consumer_credentials")
    op.drop_table("consumer_credentials")
