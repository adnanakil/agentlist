"""Ambient watched groups — groups HAL receives every message from.

Trip-independent (see HalWatchedGroup). A watched group is forwarded in full by
the bridge; the system prompt then tells HAL to stay silent unless addressed or
genuinely useful. The "..." quiet sentinel is collapsed to an empty reply in the
message route so staying silent is actually silent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalWatchedGroup

log = structlog.get_logger()


def _active(now: datetime):
    """SQL predicate for a currently-active watch: permanent (expires_at NULL)
    or not-yet-expired."""
    return or_(HalWatchedGroup.expires_at.is_(None), HalWatchedGroup.expires_at > now)


async def list_watched_chat_ids(session: AsyncSession) -> list[str]:
    now = datetime.now(timezone.utc)
    rows = (
        await session.execute(select(HalWatchedGroup.chat_id).where(_active(now)))
    ).fetchall()
    return [r[0] for r in rows]


async def is_watched(session: AsyncSession, chat_id: str | None) -> bool:
    if not chat_id:
        return False
    now = datetime.now(timezone.utc)
    stmt = select(HalWatchedGroup.id).where(
        HalWatchedGroup.chat_id == chat_id, _active(now)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def add_watched(
    session: AsyncSession,
    chat_id: str,
    note: str | None = None,
    ttl_hours: float | None = None,
) -> bool:
    """Watch a group. ttl_hours=None → permanent (manual watch, e.g. the family
    thread). ttl_hours set → auto-watch that expires; calling again REFRESHES the
    window (HAL re-engaged), so an active thread stays watched and a quiet one
    lapses back to tag-only. A permanent watch is never downgraded to a TTL."""
    now = datetime.now(timezone.utc)
    new_exp = None if ttl_hours is None else now + timedelta(hours=ttl_hours)
    row = (
        await session.execute(
            select(HalWatchedGroup).where(HalWatchedGroup.chat_id == chat_id)
        )
    ).scalar_one_or_none()
    if row is None:
        session.add(HalWatchedGroup(chat_id=chat_id, note=note, expires_at=new_exp))
        await session.flush()
        log.info("watched.added", chat_id=chat_id, ttl_hours=ttl_hours)
        return True
    if row.expires_at is None:
        return False  # already permanent — leave it
    row.expires_at = new_exp  # refresh window (or promote to permanent if None)
    if note:
        row.note = note
    await session.flush()
    return True


async def remove_watched(session: AsyncSession, chat_id: str) -> bool:
    res = await session.execute(
        delete(HalWatchedGroup).where(HalWatchedGroup.chat_id == chat_id)
    )
    await session.flush()
    return bool(res.rowcount)
