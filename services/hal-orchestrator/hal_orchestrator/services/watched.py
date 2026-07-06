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


# --------------------------------------------------------------------------- #
# Mute — "butt out" made durable.
#
# When a member tells HAL to keep out of it ("stfu", "keep it to yourself",
# "you're not invited"), the model calls group_quiet and this persists. While
# muted, the message route force-silences every non-@Hal message BEFORE the
# model can draft an interjection; explicit mentions still get through (so
# "Hal, what's the weather" works mid-mute). Orthogonal to the watch itself:
# a muted group keeps accumulating context, HAL just doesn't speak into it.
# --------------------------------------------------------------------------- #


async def is_muted(session: AsyncSession, chat_id: str | None) -> bool:
    if not chat_id:
        return False
    now = datetime.now(timezone.utc)
    stmt = select(HalWatchedGroup.id).where(
        HalWatchedGroup.chat_id == chat_id,
        HalWatchedGroup.muted_until.isnot(None),
        HalWatchedGroup.muted_until > now,
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def muted_until(session: AsyncSession, chat_id: str | None) -> datetime | None:
    """The active mute's expiry, or None when not muted."""
    if not chat_id:
        return None
    now = datetime.now(timezone.utc)
    stmt = select(HalWatchedGroup.muted_until).where(
        HalWatchedGroup.chat_id == chat_id
    )
    until = (await session.execute(stmt)).scalar_one_or_none()
    return until if until is not None and until > now else None


async def set_muted(
    session: AsyncSession, chat_id: str, days: float | None
) -> datetime | None:
    """Mute the group for `days` (creating the row if the group was never
    watched — the mute must hold even for tag-only groups). days None/<=0 →
    unmute. Returns the new muted_until (None when unmuted). Never touches
    expires_at: a permanent family watch stays permanent through a mute."""
    now = datetime.now(timezone.utc)
    new_until = now + timedelta(days=days) if days and days > 0 else None
    row = (
        await session.execute(
            select(HalWatchedGroup).where(HalWatchedGroup.chat_id == chat_id)
        )
    ).scalar_one_or_none()
    if row is None:
        # Expired-watch shell: carries the mute without turning on ambient
        # forwarding for a group that wasn't being watched.
        row = HalWatchedGroup(
            chat_id=chat_id, note="mute state", expires_at=now, muted_until=new_until
        )
        session.add(row)
    else:
        row.muted_until = new_until
    await session.flush()
    log.info("watched.muted", chat_id=chat_id, until=str(new_until))
    return new_until
