"""HAL group-context catalog: hal_group_members.

Tracks, for each (group, member) pair, that the member has actually SPOKEN in
that group — the only provable membership signal available (iMessage group
rosters can't be enumerated). Backs the group-context catalog: a ~100-token
summary of the user's group activity injected into their 1:1 prompt, plus a
scoped recall_history(group=...) pull. One-way like hal_group_observations —
group -> the member's own DM, never DM -> group and never group -> group.

Revision ID: 028
Revises: 027
Create Date: 2026-07-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_group_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("group_silo", sa.Text(), nullable=False),
        sa.Column("member_silo", sa.Text(), nullable=False),
        sa.Column("group_name", sa.Text(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_spoke_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hal_group_members_group_silo", "hal_group_members", ["group_silo"])
    op.create_index("ix_hal_group_members_member_silo", "hal_group_members", ["member_silo"])
    op.create_index(
        "ix_hal_group_members_last_spoke_at", "hal_group_members", ["last_spoke_at"]
    )
    op.create_unique_constraint(
        "uq_hal_group_members_group_member",
        "hal_group_members",
        ["group_silo", "member_silo"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_hal_group_members_group_member", "hal_group_members", type_="unique"
    )
    op.drop_index("ix_hal_group_members_last_spoke_at", table_name="hal_group_members")
    op.drop_index("ix_hal_group_members_member_silo", table_name="hal_group_members")
    op.drop_index("ix_hal_group_members_group_silo", table_name="hal_group_members")
    op.drop_table("hal_group_members")
