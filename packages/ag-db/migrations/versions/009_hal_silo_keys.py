"""Per-silo isolation: widen phone columns to hold silo keys, scope skills.

`phone` columns now hold SILO KEYS, not just phone numbers: a normalized E.164
phone or lowercased email for 1:1 chats, or the iMessage group chat id (e.g.
"chat63837193722342854…", >20 chars) for group chats. varchar(20) couldn't
hold group ids or emails, so widen to varchar(255).

hal_user_skills gains an owner column: skills become private to the silo that
created them (previously global — any user could see/invoke any other user's
skills). Existing rows predate multi-user and were all created by Adnan, so
they're backfilled to his silo. Name uniqueness becomes per-silo.

Revision ID: 009
Revises: 008
Create Date: 2026-06-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PHONE_COLS = [
    ("hal_conversations", "phone"),
    ("hal_user_profiles", "phone"),
    ("hal_user_memories", "phone"),
    ("hal_reminders", "phone"),
    ("hal_reminders", "sender_phone"),
]


def upgrade() -> None:
    for table, col in _PHONE_COLS:
        op.alter_column(table, col, type_=sa.String(255), existing_nullable=True)

    op.add_column("hal_user_skills", sa.Column("phone", sa.String(255), nullable=True))
    # Pre-multi-user rows were all Adnan's; assign them to his silo.
    op.execute("UPDATE hal_user_skills SET phone = '+12017570419' WHERE phone IS NULL")
    op.drop_constraint("hal_user_skills_name_key", "hal_user_skills", type_="unique")
    op.create_index("ix_hal_user_skills_phone", "hal_user_skills", ["phone"])
    op.create_unique_constraint(
        "uq_hal_user_skills_phone_name", "hal_user_skills", ["phone", "name"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_hal_user_skills_phone_name", "hal_user_skills", type_="unique"
    )
    op.drop_index("ix_hal_user_skills_phone", table_name="hal_user_skills")
    op.create_unique_constraint(
        "hal_user_skills_name_key", "hal_user_skills", ["name"]
    )
    op.drop_column("hal_user_skills", "phone")
    for table, col in reversed(_PHONE_COLS):
        op.alter_column(table, col, type_=sa.String(20), existing_nullable=True)
