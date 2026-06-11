"""Structured baby tracking — families + baby events.

Replaces free-text memory lines ("Bazzy fed 9:47am") with a structured event
store. A FAMILY is the one deliberate exception to silo isolation: the baby is
a shared entity, so the parents' 1:1 silos and the family group chat silo are
linked to one family and read/write the same event log. Membership is explicit
(seeded/admin or baby setup in a silo) — nothing else crosses silos.

Revision ID: 021
Revises: 020
Create Date: 2026-06-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_families",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, server_default=""),
        sa.Column("baby_name", sa.String(100), nullable=False),
        sa.Column("baby_birthdate", sa.Date, nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="America/New_York"),
        # auto_reminders, auto_wind_down, auto_feed_prep, nap_cap_minutes,
        # routines: [{after, offset_min, text}], ...
        sa.Column("settings", JSONB, nullable=False, server_default="{}"),
        # Watcher bookkeeping (e.g. last nap-cap nudge event id) — not user config.
        sa.Column("state", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "hal_family_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id",
            UUID(as_uuid=True),
            sa.ForeignKey("hal_families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Silo key (1:1 phone or group chat id). One family per silo.
        sa.Column("silo", sa.String(255), nullable=False, unique=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="parent"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hal_family_members_family", "hal_family_members", ["family_id"])

    op.create_table(
        "hal_baby_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id",
            UUID(as_uuid=True),
            sa.ForeignKey("hal_families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # feed | nap_start | wake | bedtime | tummy_time | diaper | note
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("logged_by", sa.String(255), nullable=True),  # sender phone
        sa.Column("silo", sa.String(255), nullable=False, server_default=""),  # source silo
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_hal_baby_events_family_at", "hal_baby_events", ["family_id", "event_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_hal_baby_events_family_at", table_name="hal_baby_events")
    op.drop_table("hal_baby_events")
    op.drop_index("ix_hal_family_members_family", table_name="hal_family_members")
    op.drop_table("hal_family_members")
    op.drop_table("hal_families")
