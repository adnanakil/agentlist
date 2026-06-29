"""Keyword-based search and ranking for agent discovery."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from ag_db.models import Agent, Category


async def search_agents(
    session: AsyncSession,
    query: str,
    category_slug: str | None = None,
    max_price_cents: int | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search agents using keyword matching and composite ranking.

    Matches query against agent name, description, slug, and tags (ILIKE).
    Ranking: success_rate * 0.5 + log(invocations) * 0.3 + 0.2 (base).
    """
    pattern = f"%{query}%"

    score = (
        0.5 * Agent.success_rate
        + 0.3 * func.log(func.greatest(Agent.total_invocations, 1))
        + 0.2
    ).label("score")

    stmt = (
        select(Agent, score)
        .where(Agent.status == "active")
        .where(
            or_(
                Agent.name.ilike(pattern),
                Agent.description.ilike(pattern),
                Agent.slug.ilike(pattern),
                Agent.tags.cast(sa_text()).ilike(pattern),
            )
        )
    )

    if category_slug:
        stmt = stmt.join(Category, Agent.category_id == Category.id).where(
            Category.slug == category_slug
        )

    if max_price_cents is not None:
        stmt = stmt.where(Agent.price_per_call_cents <= max_price_cents)

    stmt = stmt.order_by(score.desc()).limit(limit)
    stmt = stmt.options(joinedload(Agent.category))

    result = await session.execute(stmt)
    rows = result.unique().all()

    return [
        {
            "agent": agent,
            "score": float(agent_score) if agent_score is not None else 0.0,
        }
        for agent, agent_score in rows
    ]


async def list_active_agents(
    session: AsyncSession,
    category_slug: str | None = None,
    max_price_cents: int | None = None,
    limit: int = 10,
) -> list[dict]:
    """List all active agents (used when query is empty)."""
    stmt = select(Agent).where(Agent.status == "active")

    if category_slug:
        stmt = stmt.join(Category, Agent.category_id == Category.id).where(
            Category.slug == category_slug
        )

    if max_price_cents is not None:
        stmt = stmt.where(Agent.price_per_call_cents <= max_price_cents)

    stmt = stmt.order_by(Agent.total_invocations.desc()).limit(limit)
    stmt = stmt.options(joinedload(Agent.category))

    result = await session.execute(stmt)
    agents = result.unique().scalars().all()

    return [{"agent": agent, "score": 0.0} for agent in agents]


async def get_agent_by_id(session: AsyncSession, agent_id: uuid.UUID) -> Agent | None:
    stmt = (
        select(Agent)
        .where(Agent.id == agent_id)
        .options(joinedload(Agent.category))
    )
    result = await session.execute(stmt)
    return result.unique().scalar_one_or_none()


async def get_agent_by_slug(session: AsyncSession, slug: str) -> Agent | None:
    stmt = (
        select(Agent)
        .where(Agent.slug == slug)
        .options(joinedload(Agent.category))
    )
    result = await session.execute(stmt)
    return result.unique().scalar_one_or_none()


def sa_text():
    """Helper to get SQLAlchemy Text type for casting JSONB."""
    from sqlalchemy import Text
    return Text()
