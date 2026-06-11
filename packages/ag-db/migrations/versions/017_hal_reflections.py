"""Nightly reflection reports (auto-created skills + feature proposals).

Revision ID: 017
Revises: 016
Create Date: 2026-06-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_reflections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("summary", sa.Text, nullable=False, server_default=""),
        sa.Column("report", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hal_reflections_created", "hal_reflections", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_hal_reflections_created", table_name="hal_reflections")
    op.drop_table("hal_reflections")
