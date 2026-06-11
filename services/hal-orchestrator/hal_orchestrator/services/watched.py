"""Ambient watched groups — groups HAL receives every message from.

Trip-independent (see HalWatchedGroup). A watched group is forwarded in full by
the bridge; the system prompt then tells HAL to stay silent unless addressed or
genuinely useful. The "..." quiet sentinel is collapsed to an empty reply in the
message route so staying silent is actually silent.
"""

from __future__ import annotations

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalWatchedGroup

log = structlog.get_logger()


async def list_watched_chat_ids(session: AsyncSession) -> list[str]:
    rows = (await session.execute(select(HalWatchedGroup.chat_id))).fetchall()
    return [r[0] for r in rows]


async def is_watched(session: AsyncSession, chat_id: str | None) -> bool:
    if not chat_id:
        return False
    stmt = select(HalWatchedGroup.id).where(HalWatchedGroup.chat_id == chat_id)
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def add_watched(
    session: AsyncSession, chat_id: str, note: str | None = None
) -> bool:
    if await is_watched(session, chat_id):
        return False
    session.add(HalWatchedGroup(chat_id=chat_id, note=note))
    await session.flush()
    log.info("watched.added", chat_id=chat_id)
    return True


async def remove_watched(session: AsyncSession, chat_id: str) -> bool:
    res = await session.execute(
        delete(HalWatchedGroup).where(HalWatchedGroup.chat_id == chat_id)
    )
    await session.flush()
    return bool(res.rowcount)
