"""Self-cancelling reminders: a natural-language validity condition.

Auto-reminders (and, optionally, manual ones) are scheduled ahead of a
*predicted* event — wind-down before the next nap, bottle prep before the next
feed. When reality diverges (baby goes down early, feeds early, skips the nap)
the clock fired them anyway, so HAL would tell you to "start winding Bazzy down"
after he was already asleep.

`cancel_if` stores, in plain language, when the reminder becomes moot. At fire
time HAL re-evaluates it against live state and drops (or rewords) the reminder
instead of sending something stale. NULL = always send (the old clock behaviour).

Revision ID: 026
Revises: 025
Create Date: 2026-06-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hal_reminders",
        sa.Column("cancel_if", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hal_reminders", "cancel_if")
