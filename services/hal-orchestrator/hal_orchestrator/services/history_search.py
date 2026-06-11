"""Cross-session full-text + temporal recall over the message archive.

Backs the recall_history tool: keyword search (Postgres FTS) + optional time
scoping over every text turn HAL has exchanged in a silo, beyond the trimmed
rolling window. Keyed by silo, so isolation holds (a user only searches their
own history; a group only its own).
"""

from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalMessage

log = structlog.get_logger()

MAX_CONTENT_CHARS = 8000


async def archive_turn(session: AsyncSession, phone: str, role: str, content: str) -> None:
    """Append one text turn to the durable archive. Best-effort; callers wrap
    this so it can never break the live reply path."""
    content = (content or "").strip()
    if not content:
        return
    session.add(
        HalMessage(phone=phone, role=role, content=content[:MAX_CONTENT_CHARS])
    )
    await session.flush()


async def search_history(
    session: AsyncSession,
    phone: str,
    query: str = "",
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 10,
) -> list[dict]:
    """Return matching archived turns for the silo (most recent first)."""
    conds = [HalMessage.phone == phone]
    if query and query.strip():
        conds.append(
            func.to_tsvector("english", HalMessage.content).op("@@")(
                func.plainto_tsquery("english", query)
            )
        )
    if since is not None:
        conds.append(HalMessage.created_at >= since)
    if until is not None:
        conds.append(HalMessage.created_at <= until)

    stmt = (
        select(HalMessage)
        .where(and_(*conds))
        .order_by(HalMessage.created_at.desc())
        .limit(max(1, min(limit, 30)))
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "role": r.role,
            "content": r.content,
            "at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
