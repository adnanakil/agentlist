"""Funnel events: UTM columns on page hits + sms-tap event table.

Adds utm_source, utm_medium, utm_campaign, attribution_code to
hal_page_hits (nullable — rows predating this migration stay valid).
Creates hal_funnel_events for post-landing events (sms_tap first).

Revision ID: 033
Revises: 032
Create Date: 2026-08-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "033"
down_revision: Union[str, None] = "032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hal_page_hits", sa.Column("utm_source", sa.String(255), nullable=True))
    op.add_column("hal_page_hits", sa.Column("utm_medium", sa.String(255), nullable=True))
    op.add_column("hal_page_hits", sa.Column("utm_campaign", sa.String(255), nullable=True))
    op.add_column("hal_page_hits", sa.Column("attribution_code", sa.String(64), nullable=True))
    op.create_index("ix_hal_page_hits_utm_source", "hal_page_hits", ["utm_source"])

    op.create_table(
        "hal_funnel_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("attribution_code", sa.String(64), nullable=True),
        sa.Column("utm_source", sa.String(255), nullable=True),
        sa.Column("utm_medium", sa.String(255), nullable=True),
        sa.Column("utm_campaign", sa.String(255), nullable=True),
        sa.Column("visitor_hash", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_hal_funnel_events_created_at", "hal_funnel_events", ["created_at"])
    op.create_index("ix_hal_funnel_events_event_type", "hal_funnel_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_hal_funnel_events_event_type", table_name="hal_funnel_events")
    op.drop_index("ix_hal_funnel_events_created_at", table_name="hal_funnel_events")
    op.drop_table("hal_funnel_events")

    op.drop_index("ix_hal_page_hits_utm_source", table_name="hal_page_hits")
    op.drop_column("hal_page_hits", "attribution_code")
    op.drop_column("hal_page_hits", "utm_campaign")
    op.drop_column("hal_page_hits", "utm_medium")
    op.drop_column("hal_page_hits", "utm_source")
