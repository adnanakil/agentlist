"""Per-user memory — remember, recall, list (Postgres)."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalUserMemory

log = structlog.get_logger()


async def remember(
    session: AsyncSession,
    phone: str,
    content: str,
    client=None,
    settings=None,
) -> str:
    """Store a memory for a user. If client+settings are given, also store a
    semantic embedding for later relevance retrieval."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    entry = f"[{ts}] {content}"

    embedding = None
    if client is not None and settings is not None:
        from hal_orchestrator.services.embeddings import embed_text

        embedding = await embed_text(client, settings, content)

    memory = HalUserMemory(phone=phone, content=entry, embedding=embedding)
    session.add(memory)
    await session.flush()

    import hal_orchestrator.state as _state

    log.info(
        "memory.remember",
        phone=phone,
        content=content[:50] if _state.settings.log_message_content else None,
        content_len=len(content or ""),
        embedded=embedding is not None,
    )
    return f"Remembered: {content}"


async def retrieve_relevant(
    session: AsyncSession,
    phone: str,
    query: str,
    client,
    settings,
    k: int = 5,
    min_score: float = 0.55,
    since=None,
) -> list[str]:
    """Return up to k stored memories most semantically relevant to `query`
    (app-side cosine over embeddings). Memories without an embedding are
    skipped. `since` floors by created_at — group silos pass their membership
    epoch so pre-epoch free text can't reach a post-cut room."""
    from hal_orchestrator.services.embeddings import cosine, embed_text

    qvec = await embed_text(client, settings, query)
    if not qvec:
        return []

    stmt = select(HalUserMemory).where(HalUserMemory.phone == phone)
    if since is not None:
        stmt = stmt.where(HalUserMemory.created_at >= since)
    rows = (await session.execute(stmt)).scalars().all()

    scored: list[tuple[float, str]] = []
    for m in rows:
        if m.embedding:
            s = cosine(qvec, m.embedding)
            if s >= min_score:
                scored.append((s, m.content))

    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:k]]


async def recall(
    session: AsyncSession, phone: str, query: str, since=None
) -> str:
    """Search user's memories for matching content. `since` floors by
    created_at (group membership epoch)."""
    stmt = (
        select(HalUserMemory)
        .where(HalUserMemory.phone == phone)
        .order_by(HalUserMemory.created_at.desc())
    )
    if since is not None:
        stmt = stmt.where(HalUserMemory.created_at >= since)
    result = await session.execute(stmt)
    memories = result.scalars().all()

    query_lower = query.lower()
    matches = [m.content for m in memories if query_lower in m.content.lower()]

    if not matches:
        return f"No memories found matching '{query}'."

    # Return last 5 matches
    recent = matches[:5]
    return "Found memories:\n" + "\n".join(f"- {m}" for m in recent)


async def list_memories(
    session: AsyncSession, phone: str, since=None
) -> str:
    """List recent memories for a user. `since` floors by created_at (group
    membership epoch)."""
    stmt = (
        select(HalUserMemory)
        .where(HalUserMemory.phone == phone)
        .order_by(HalUserMemory.created_at.desc())
        .limit(10)
    )
    if since is not None:
        stmt = stmt.where(HalUserMemory.created_at >= since)
    result = await session.execute(stmt)
    memories = result.scalars().all()

    if not memories:
        return "No memories stored yet."

    lines = [m.content for m in memories]
    return "Recent memories:\n" + "\n".join(f"- {line}" for line in lines)
