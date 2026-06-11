"""Growth loop — universal turn capture, self-authored playbook, feature backlog.

See services/hal-orchestrator/GROWTH.md. hal_turns records EVERY turn (data
plane, per-silo) so the nightly grader can assess them in-silo; hal_playbook
and hal_feature_backlog are the global learning plane's outputs.

Revision ID: 022
Revises: 021
Create Date: 2026-06-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hal_turns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(255), nullable=False),  # silo
        sa.Column("sender_phone", sa.String(255), nullable=True),
        sa.Column("user_text", sa.Text, nullable=False, server_default=""),
        sa.Column("reply", sa.Text, nullable=False, server_default=""),
        # [{tool, args:[names]}] — includes delegated agent in args when present
        sa.Column("steps", JSONB, nullable=False, server_default="[]"),
        # ok | gemini_failed | quiet
        sa.Column("status", sa.String(24), nullable=False, server_default="ok"),
        # graded nightly: handled | partial | failed | na
        sa.Column("grade", sa.String(16), nullable=True),
        # missing_tool | missing_knowledge | missing_data_access | bad_judgment |
        # external_block | ambiguous_request | infra_error
        sa.Column("failure_category", sa.String(32), nullable=True),
        sa.Column("grade_note", sa.Text, nullable=False, server_default=""),
        # conversation-level signals the grader attached (correction, re_ask, ...)
        sa.Column("signals", JSONB, nullable=False, server_default="[]"),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hal_turns_ungraded", "hal_turns", ["graded_at", "created_at"])
    op.create_index("ix_hal_turns_phone_created", "hal_turns", ["phone", "created_at"])

    op.create_table(
        "hal_playbook",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("content", sa.Text, nullable=False),
        # The falsifiable claim: which failure this entry should eliminate.
        sa.Column("hypothesis", sa.Text, nullable=False, server_default=""),
        sa.Column("target_category", sa.String(32), nullable=True),
        sa.Column("target_detail", sa.String(200), nullable=True),
        # active | verified | failing | reverted | retired
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("origin_reflection_id", UUID(as_uuid=True), nullable=True),
        sa.Column("clean_nights", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fail_nights", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hal_playbook_status", "hal_playbook", ["status"])

    op.create_table(
        "hal_feature_backlog",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("problem", sa.Text, nullable=False, server_default=""),
        # [{date, signal, count}] — accumulated, redacted evidence
        sa.Column("evidence", JSONB, nullable=False, server_default="[]"),
        sa.Column("sketch", sa.Text, nullable=False, server_default=""),
        # Fuller build spec drafted once priority/evidence warrants it.
        sa.Column("spec", sa.Text, nullable=False, server_default=""),
        sa.Column("priority", sa.String(8), nullable=False, server_default="medium"),
        # open | notified | greenlit | built | rejected
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("evidence_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_hal_feature_backlog_status", "hal_feature_backlog", ["status"])


def downgrade() -> None:
    op.drop_index("ix_hal_feature_backlog_status", table_name="hal_feature_backlog")
    op.drop_table("hal_feature_backlog")
    op.drop_index("ix_hal_playbook_status", table_name="hal_playbook")
    op.drop_table("hal_playbook")
    op.drop_index("ix_hal_turns_phone_created", table_name="hal_turns")
    op.drop_index("ix_hal_turns_ungraded", table_name="hal_turns")
    op.drop_table("hal_turns")
