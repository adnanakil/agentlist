"""Group-chat hardening: persistent mute, DM/group-scoped playbook, follow-ups.

Three related additions from the 2026-07-05 group-restraint hardening pass:

- hal_watched_groups.muted_until: a user telling HAL to butt out ("stfu",
  "keep it to yourself") now persists. While muted, non-@Hal messages in the
  group are code-forced silent (no model draft to leak); mentions still get
  answered. NULL = not muted.

- hal_playbook.scope: playbook rules learned from 1:1 behavior were injected
  into group turns too — the June 19 "always acknowledge reports" rule (learned
  from baby logging) directly fought the ambient-watch silence default and
  produced group interjections. Rules now carry 'dm' | 'group' | 'all' and the
  injector filters by silo type.

- hal_followups: tracks post-event check-ins the follow-up sweep has sent
  (phase 'checkin' = "how did it go", phase 'suggest' = a later "want to do
  something again" ping), so an event is never followed up twice.

Revision ID: 027
Revises: 026
Create Date: 2026-07-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hal_watched_groups",
        sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "hal_playbook",
        sa.Column("scope", sa.String(8), nullable=False, server_default="all"),
    )
    op.create_table(
        "hal_followups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("silo", sa.String(255), nullable=False),
        sa.Column("event_key", sa.String(200), nullable=False),
        sa.Column("event_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_hal_followups_silo_event", "hal_followups", ["silo", "event_at"])
    op.create_unique_constraint(
        "uq_hal_followups_silo_key_phase", "hal_followups", ["silo", "event_key", "phase"]
    )


def downgrade() -> None:
    op.drop_table("hal_followups")
    op.drop_column("hal_playbook", "scope")
    op.drop_column("hal_watched_groups", "muted_until")
