"""Outbox image attachments.

Nullable JSONB list of {mime_type, data(base64), ext} on hal_outbox_messages so
proactive sends (cron digests) can ship rendered cards as real iMessage
attachments. Additive and nullable: bridges that predate the field keep
working, and downgrade is a plain column drop.

Revision ID: 030
Revises: 029
Create Date: 2026-07-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hal_outbox_messages",
        sa.Column("images", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hal_outbox_messages", "images")
