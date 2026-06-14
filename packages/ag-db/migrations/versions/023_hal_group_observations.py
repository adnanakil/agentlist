"""Group observations — one-way valve from group chats to members' personal silos.

Written only by the group-side profile enricher (facts about a member sourced
from a group conversation they spoke in); read only when building a member's
1:1 context. The group agent never reads it; personal data never flows back.

Revision ID: 023
Revises: 022
Create Date: 2026-06-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_group_observations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("member_phone", sa.String(255), nullable=False),
        sa.Column("group_silo", sa.String(255), nullable=False),
        sa.Column("group_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_hal_group_obs_member_created",
        "hal_group_observations",
        ["member_phone", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hal_group_obs_member_created", table_name="hal_group_observations"
    )
    op.drop_table("hal_group_observations")
