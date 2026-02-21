"""Per-user memory — remember, recall, list (Postgres)."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalUserMemory

log = structlog.get_logger()


async def remember(session: AsyncSession, phone: str, content: str) -> str:
    """Store a memory for a user."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    entry = f"[{ts}] {content}"

    memory = HalUserMemory(phone=phone, content=entry)
    session.add(memory)
    await session.flush()

    log.info("memory.remember", phone=phone, content=content[:50])
    return f"Remembered: {content}"


async def recall(session: AsyncSession, phone: str, query: str) -> str:
    """Search user's memories for matching content."""
    stmt = (
        select(HalUserMemory)
        .where(HalUserMemory.phone == phone)
        .order_by(HalUserMemory.created_at.desc())
    )
    result = await session.execute(stmt)
    memories = result.scalars().all()

    query_lower = query.lower()
    matches = [m.content for m in memories if query_lower in m.content.lower()]

    if not matches:
        return f"No memories found matching '{query}'."

    # Return last 5 matches
    recent = matches[:5]
    return "Found memories:\n" + "\n".join(f"- {m}" for m in recent)


async def list_memories(session: AsyncSession, phone: str) -> str:
    """List recent memories for a user."""
    stmt = (
        select(HalUserMemory)
        .where(HalUserMemory.phone == phone)
        .order_by(HalUserMemory.created_at.desc())
        .limit(10)
    )
    result = await session.execute(stmt)
    memories = result.scalars().all()

    if not memories:
        return "No memories stored yet."

    lines = [m.content for m in memories]
    return "Recent memories:\n" + "\n".join(f"- {line}" for line in lines)
