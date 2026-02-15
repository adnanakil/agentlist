"""Semantic search and ranking for agent discovery."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from ag_db.models import Agent, Category


async def search_agents(
    session: AsyncSession,
    query_embedding: list[float],
    category_slug: str | None = None,
    max_price_cents: int | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search agents using semantic similarity and composite ranking.

    The ranking score combines:
      - 40% semantic similarity (1 - cosine_distance)
      - 30% success rate
      - 20% rating placeholder (fixed 0.5 for MVP)
      - 10% popularity (log of total invocations)

    Args:
        session: Async database session.
        query_embedding: The query embedding vector (1536 floats).
        category_slug: Optional category slug to filter by.
        max_price_cents: Optional maximum price filter.
        limit: Maximum number of results to return.

    Returns:
        List of dicts with agent data and computed score.
    """
    cosine_dist = Agent.description_embedding.cosine_distance(query_embedding)
    similarity = (1 - cosine_dist).label("similarity")

    score = (
        0.4 * (1 - cosine_dist)
        + 0.3 * Agent.success_rate
        + 0.2 * 0.5
        + 0.1 * func.log(func.greatest(Agent.total_invocations, 1))
    ).label("score")

    stmt = (
        select(Agent, score, similarity)
        .where(Agent.status == "active")
        .where(Agent.description_embedding.is_not(None))
    )

    if category_slug:
        stmt = stmt.join(Category, Agent.category_id == Category.id).where(
            Category.slug == category_slug
        )

    if max_price_cents is not None:
        stmt = stmt.where(Agent.price_per_call_cents <= max_price_cents)

    stmt = stmt.order_by(score.desc()).limit(limit)

    # We also need the category relationship loaded for building responses
    stmt = stmt.options(joinedload(Agent.category))

    result = await session.execute(stmt)
    rows = result.unique().all()

    agents = []
    for agent, agent_score, agent_similarity in rows:
        agents.append(
            {
                "agent": agent,
                "score": float(agent_score) if agent_score is not None else 0.0,
                "similarity": float(agent_similarity) if agent_similarity is not None else 0.0,
            }
        )

    return agents


async def get_agent_by_id(session: AsyncSession, agent_id: uuid.UUID) -> Agent | None:
    """Fetch a single agent by its UUID, eagerly loading the category.

    Args:
        session: Async database session.
        agent_id: The agent's primary key UUID.

    Returns:
        The Agent ORM instance, or None if not found.
    """
    stmt = (
        select(Agent)
        .where(Agent.id == agent_id)
        .options(joinedload(Agent.category))
    )
    result = await session.execute(stmt)
    return result.unique().scalar_one_or_none()


async def get_agent_by_slug(session: AsyncSession, slug: str) -> Agent | None:
    """Fetch a single agent by its unique slug, eagerly loading the category.

    Args:
        session: Async database session.
        slug: The agent's unique slug.

    Returns:
        The Agent ORM instance, or None if not found.
    """
    stmt = (
        select(Agent)
        .where(Agent.slug == slug)
        .options(joinedload(Agent.category))
    )
    result = await session.execute(stmt)
    return result.unique().scalar_one_or_none()
