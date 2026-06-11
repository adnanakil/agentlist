"""Per-silo Google OAuth token store (encrypted at rest).

Adds hal_google_accounts so each silo (a user's 1:1 chat) can connect its own
Google account for read-only Calendar + Gmail. Tokens are Fernet-encrypted by
the app before storage; this table never holds plaintext.

Revision ID: 010
Revises: 009
Create Date: 2026-06-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_google_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(255), nullable=False, unique=True),
        sa.Column("google_email", sa.String(320), nullable=True),
        sa.Column("access_token_enc", sa.Text, nullable=False, server_default=""),
        sa.Column("refresh_token_enc", sa.Text, nullable=True),
        sa.Column("token_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hal_google_accounts_phone", "hal_google_accounts", ["phone"])


def downgrade() -> None:
    op.drop_index("ix_hal_google_accounts_phone", table_name="hal_google_accounts")
    op.drop_table("hal_google_accounts")
