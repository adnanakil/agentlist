"""Auto-watch groups with a TTL.

HAL only receives group messages that tag "Hal" (unless the group is watched).
So an answer to HAL's OWN question, or a follow-up instruction, that doesn't say
"Hal" is dropped — HAL never sees it. This adds `expires_at` so HAL can watch a
group *while it's actively coordinating there* (it just replied) and have the
watch lapse back to tag-only afterwards. NULL = permanent (manually watched,
e.g. the family thread); a timestamp = auto-watch that expires if HAL doesn't
engage again.

Revision ID: 025
Revises: 024
Create Date: 2026-06-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hal_watched_groups",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hal_watched_groups", "expires_at")
