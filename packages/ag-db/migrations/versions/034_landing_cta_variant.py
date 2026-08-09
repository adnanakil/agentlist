"""Landing hero-CTA A/B: record which CTA copy each visitor was served.

Adds a nullable `variant` to hal_page_hits (what was rendered) and
hal_funnel_events (what the tapped page was rendered with). Nullable so every
row predating the experiment stays valid and reads as "not in the experiment".

Revision ID: 034
Revises: 033
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "034"
down_revision: Union[str, None] = "033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hal_page_hits", sa.Column("variant", sa.String(8), nullable=True))
    op.add_column("hal_funnel_events", sa.Column("variant", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("hal_funnel_events", "variant")
    op.drop_column("hal_page_hits", "variant")
