"""First-party landing-site page views.

`hal_page_hits` records one row per GET of the public pages (/, /privacy,
/terms), written server-side by the orchestrator — no client JS or cookies,
consistent with the site's no-tracking promise. `visitor_hash` is a
day-salted sha256 of (ip, user_agent) so daily uniques are countable
without ever storing an IP. Bots are flagged (`is_bot`), not dropped.

Revision ID: 032
Revises: 031
Create Date: 2026-07-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "032"
down_revision: Union[str, None] = "031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_page_hits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("path", sa.String(255), nullable=False),
        sa.Column("referrer", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("visitor_hash", sa.String(16), nullable=False),
        sa.Column("is_bot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_hal_page_hits_created_at", "hal_page_hits", ["created_at"])
    op.create_index("ix_hal_page_hits_path", "hal_page_hits", ["path"])


def downgrade() -> None:
    op.drop_index("ix_hal_page_hits_path", table_name="hal_page_hits")
    op.drop_index("ix_hal_page_hits_created_at", table_name="hal_page_hits")
    op.drop_table("hal_page_hits")
