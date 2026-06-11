"""Add hal_trips table for trip coordination.

Revision ID: 006
Revises: 005
Create Date: 2026-03-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_trips",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("chat_id", sa.String(200), nullable=False),
        sa.Column("location", sa.Text, nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="collecting",
        ),
        sa.Column("created_by", sa.String(20), nullable=True),
        sa.Column("participants", JSONB, nullable=False, server_default="{}"),
        sa.Column("locked_dates", JSONB, nullable=True),
        sa.Column("options", JSONB, nullable=False, server_default="[]"),
        sa.Column("votes", JSONB, nullable=False, server_default="{}"),
        sa.Column("winner", JSONB, nullable=True),
        sa.Column("group_name", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_hal_trips_chat_id", "hal_trips", ["chat_id"])
    op.create_index("ix_hal_trips_status", "hal_trips", ["status"])


def downgrade() -> None:
    op.drop_index("ix_hal_trips_status", table_name="hal_trips")
    op.drop_index("ix_hal_trips_chat_id", table_name="hal_trips")
    op.drop_table("hal_trips")
