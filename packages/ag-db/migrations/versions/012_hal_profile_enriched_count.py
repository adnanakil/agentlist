"""Add hal_user_profiles.enriched_at_count for the background profile enricher.

The enricher daemon distills durable preferences/needs (1:1) or interests/
dynamics/goals (group) from a silo's conversation into its structured profile.
This counter records the conversation message_count at the last enrichment so it
only re-runs after enough new activity.

Revision ID: 012
Revises: 011
Create Date: 2026-06-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hal_user_profiles",
        sa.Column(
            "enriched_at_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("hal_user_profiles", "enriched_at_count")
