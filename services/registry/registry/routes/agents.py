"""Internal CRUD and discovery routes for agents."""

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.errors import NotFoundError, ValidationError
from ag_common.models import (
    AgentDetail,
    AgentRuntime,
    AgentSummary,
    DiscoverRequest,
    DiscoverResponse,
    HealthResponse,
)
from ag_db.models import Agent, Category
from ag_db.session import get_session

from registry.services.embedding import generate_embedding
from registry.services.matching import get_agent_by_id, get_agent_by_slug, search_agents
from registry.services.validation import validate_manifest

log = structlog.get_logger()

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models (internal-only, not in ag_common)
# ---------------------------------------------------------------------------


class CreateAgentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str = Field(min_length=1)
    developer_id: UUID
    category_slug: str | None = None
    price_per_call_cents: int = Field(default=0, ge=0)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any]
    tags: list[str] = Field(default_factory=list)
    version: str = "0.1.0"
    runtime: AgentRuntime = AgentRuntime.python


class UpdateAgentRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    price_per_call_cents: int | None = None
    input_schema: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
    tags: list[str] | None = None
    version: str | None = None
    image_uri: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_to_summary(agent: Agent, score: float | None = None) -> AgentSummary:
    """Convert an Agent ORM instance to an AgentSummary Pydantic model."""
    return AgentSummary(
        id=agent.id,
        slug=agent.slug,
        name=agent.name,
        description=agent.description,
        category=agent.category.slug if agent.category else "",
        price_per_call_cents=agent.price_per_call_cents,
        tags=agent.tags or [],
        total_invocations=agent.total_invocations,
        success_rate=agent.success_rate,
        avg_latency_ms=agent.avg_latency_ms,
        score=score,
    )


def _agent_to_detail(agent: Agent) -> AgentDetail:
    """Convert an Agent ORM instance to an AgentDetail Pydantic model."""
    return AgentDetail(
        id=agent.id,
        slug=agent.slug,
        name=agent.name,
        description=agent.description,
        category=agent.category.slug if agent.category else "",
        price_per_call_cents=agent.price_per_call_cents,
        tags=agent.tags or [],
        total_invocations=agent.total_invocations,
        success_rate=agent.success_rate,
        avg_latency_ms=agent.avg_latency_ms,
        version=agent.version,
        runtime=AgentRuntime(agent.runtime),
        input_schema=agent.input_schema or {},
        created_at=agent.created_at,
    )


async def _resolve_category(session: AsyncSession, category_slug: str | None) -> UUID | None:
    """Look up a category by slug and return its id, or None."""
    if not category_slug:
        return None
    result = await session.execute(
        select(Category).where(Category.slug == category_slug)
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise NotFoundError(f"Category '{category_slug}' not found")
    return category.id


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/internal/agents", response_model=AgentDetail, status_code=201)
async def create_agent(
    body: CreateAgentRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AgentDetail:
    """Create a new agent in the registry.

    Validates the manifest, generates a description embedding, resolves the
    category, and persists the Agent row.
    """
    # Validate manifest
    manifest_errors = validate_manifest(body.manifest)
    if manifest_errors:
        raise ValidationError(
            "Invalid agent manifest",
            details={"errors": manifest_errors},
        )

    # Generate description embedding
    openai_client = request.app.state.openai_client
    embedding = await generate_embedding(body.description, openai_client)

    # Resolve category
    category_id = await _resolve_category(session, body.category_slug)

    # Create agent row
    agent = Agent(
        developer_id=body.developer_id,
        category_id=category_id,
        slug=body.slug,
        name=body.name,
        description=body.description,
        version=body.version,
        runtime=body.runtime.value,
        status="draft",
        price_per_call_cents=body.price_per_call_cents,
        input_schema=body.input_schema,
        manifest=body.manifest,
        description_embedding=embedding,
        tags=body.tags,
    )

    session.add(agent)
    await session.commit()
    await session.refresh(agent, attribute_names=["category"])

    log.info("agent.created", agent_id=str(agent.id), slug=agent.slug)
    return _agent_to_detail(agent)


@router.get("/internal/agents/{agent_id}", response_model=AgentDetail)
async def get_agent(
    agent_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> AgentDetail:
    """Retrieve a single agent by its UUID."""
    agent = await get_agent_by_id(session, agent_id)
    if agent is None:
        raise NotFoundError(f"Agent '{agent_id}' not found")
    return _agent_to_detail(agent)


@router.patch("/internal/agents/{agent_id}", response_model=AgentDetail)
async def update_agent(
    agent_id: UUID,
    body: UpdateAgentRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AgentDetail:
    """Update an existing agent's fields.

    Supports partial updates. If the description changes, a new embedding is
    generated. If a new manifest is provided, it is validated before persisting.
    """
    agent = await get_agent_by_id(session, agent_id)
    if agent is None:
        raise NotFoundError(f"Agent '{agent_id}' not found")

    update_data = body.model_dump(exclude_unset=True)

    # Validate manifest if provided
    if "manifest" in update_data and update_data["manifest"] is not None:
        manifest_errors = validate_manifest(update_data["manifest"])
        if manifest_errors:
            raise ValidationError(
                "Invalid agent manifest",
                details={"errors": manifest_errors},
            )

    # Re-generate embedding if description changed
    if "description" in update_data and update_data["description"] is not None:
        openai_client = request.app.state.openai_client
        embedding = await generate_embedding(update_data["description"], openai_client)
        agent.description_embedding = embedding

    # Apply all provided fields
    for field, value in update_data.items():
        if value is not None and hasattr(agent, field):
            setattr(agent, field, value)

    await session.commit()
    await session.refresh(agent, attribute_names=["category"])

    log.info("agent.updated", agent_id=str(agent.id), fields=list(update_data.keys()))
    return _agent_to_detail(agent)


@router.post("/internal/discover", response_model=DiscoverResponse)
async def discover_agents(
    body: DiscoverRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> DiscoverResponse:
    """Semantic search for agents.

    Generates an embedding from the query, runs a composite-ranked search
    against the agents table, and returns matching AgentSummary objects.
    """
    openai_client = request.app.state.openai_client
    query_embedding = await generate_embedding(body.query, openai_client)

    results = await search_agents(
        session=session,
        query_embedding=query_embedding,
        category_slug=body.category,
        max_price_cents=body.max_price_cents,
        limit=body.limit,
    )

    agents = [
        _agent_to_summary(row["agent"], score=row["score"])
        for row in results
    ]

    log.info(
        "discover.search",
        query=body.query,
        category=body.category,
        results=len(agents),
    )

    return DiscoverResponse(agents=agents, total=len(agents))


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok", service="registry", version="0.1.0")
