"""Orchestrator service — FastAPI application factory.

Handles the full agent invocation lifecycle:
1. Validate request & look up agent
2. Create invocation record (status=pending)
3. Place billing hold
4. Execute agent container via Docker runtime
5. Settle or release hold based on outcome
6. Return InvokeResponse
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID

import httpx
import structlog
import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Header
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import OrchestratorConfig
from ag_common.errors import (
    AgentGateError,
    InsufficientFundsError,
    NotFoundError,
    ValidationError,
    agentgate_error_handler,
)
from ag_common.models import (
    HealthResponse,
    InvocationStatus,
    InvokeRequest,
    InvokeResponse,
)
from ag_db.models import Agent, Invocation
from ag_db.session import create_engine_and_session, get_session

from orchestrator.runtime.docker_runtime import DockerRuntime
from orchestrator.tasks.invoke import get_agent_credentials

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()
settings = OrchestratorConfig()

# --------------------------------------------------------------------------- #
# Shared objects
# --------------------------------------------------------------------------- #

runtime = DockerRuntime()
http_client: httpx.AsyncClient | None = None


# --------------------------------------------------------------------------- #
# Lifespan
# --------------------------------------------------------------------------- #


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global http_client

    log.info("orchestrator.startup", database_url=settings.database_url[:30] + "...")
    engine, _ = create_engine_and_session(settings.database_url)
    app.state.config = settings

    http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    yield

    log.info("orchestrator.shutdown")
    if http_client:
        await http_client.aclose()
    await engine.dispose()


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentGate Orchestrator",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_exception_handler(AgentGateError, agentgate_error_handler)

    app.include_router(_build_router())

    return app


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #

def _build_router() -> APIRouter:
    router = APIRouter()

    # ---- Health ----------------------------------------------------------- #

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="orchestrator")

    # ---- Invoke ----------------------------------------------------------- #

    @router.post("/internal/invoke", response_model=InvokeResponse)
    async def invoke(
        body: InvokeRequest,
        x_account_id: str = Header(..., alias="X-Account-ID"),
        session: AsyncSession = Depends(get_session),
    ) -> InvokeResponse:
        consumer_id = _parse_uuid(x_account_id, "X-Account-ID")

        # 1. Look up agent by id or slug
        agent = await _resolve_agent(session, body.agent_id, body.agent_slug)

        # 2. Validate input against agent's input_schema (lightweight check)
        _validate_input(body.input, agent.input_schema)

        # 3. Create invocation record (pending)
        invocation = Invocation(
            consumer_id=consumer_id,
            agent_id=agent.id,
            status=InvocationStatus.pending.value,
            input=body.input,
            price_cents=agent.price_per_call_cents,
        )
        session.add(invocation)
        await session.flush()  # populate invocation.id

        log.info(
            "invoke.created",
            invocation_id=str(invocation.id),
            agent_id=str(agent.id),
            consumer_id=str(consumer_id),
        )

        # 4. Place billing hold
        hold_id = await _place_hold(
            consumer_id=consumer_id,
            amount_cents=agent.price_per_call_cents,
            invocation_id=invocation.id,
        )
        invocation.hold_id = hold_id
        await session.flush()

        # 5. Execute agent
        try:
            invocation.status = InvocationStatus.running.value
            await session.flush()

            # Decrypt agent credentials to pass as env vars
            credentials = await get_agent_credentials(
                session, agent.id, settings.encryption_key
            )

            result = await runtime.execute(
                image_uri=agent.image_uri or f"agentgate/agent-{agent.slug}:latest",
                input_data=body.input,
                env_vars=credentials,
                timeout_seconds=settings.agent_timeout_seconds,
                memory_limit_mb=settings.agent_memory_limit_mb,
                cpu_limit=settings.agent_cpu_limit,
            )
        except Exception as exc:
            # Platform-level error (Docker unavailable, etc.)
            log.error(
                "invoke.platform_error",
                invocation_id=str(invocation.id),
                error=str(exc),
                exc_info=True,
            )
            invocation.status = InvocationStatus.error.value
            invocation.error_message = f"Platform error: {exc}"
            invocation.completed_at = _utcnow()
            await session.commit()
            await _release_hold(hold_id)
            raise AgentGateError(
                message="Internal platform error during agent execution",
                details={"invocation_id": str(invocation.id)},
            ) from exc

        # 6. Process result
        invocation.duration_ms = result.duration_ms

        if result.error == "timeout":
            invocation.status = InvocationStatus.timeout.value
            invocation.error_message = "Agent execution timed out"
            invocation.completed_at = _utcnow()
            await session.commit()
            await _release_hold(hold_id)

            log.warning(
                "invoke.timeout",
                invocation_id=str(invocation.id),
                duration_ms=result.duration_ms,
            )

            return InvokeResponse(
                invocation_id=invocation.id,
                status=InvocationStatus.timeout,
                error="Agent execution timed out",
                duration_ms=result.duration_ms,
                price_cents=0,
            )

        if not result.success:
            invocation.status = InvocationStatus.failed.value
            invocation.error_message = result.error
            invocation.completed_at = _utcnow()
            await session.commit()
            await _release_hold(hold_id)

            log.warning(
                "invoke.failed",
                invocation_id=str(invocation.id),
                error=result.error,
            )

            return InvokeResponse(
                invocation_id=invocation.id,
                status=InvocationStatus.failed,
                error=result.error,
                duration_ms=result.duration_ms,
                price_cents=0,
            )

        # Success path
        invocation.status = InvocationStatus.completed.value
        invocation.output = result.output
        invocation.completed_at = _utcnow()
        await session.commit()

        await _settle_hold(hold_id, developer_account_id=agent.developer_id)

        log.info(
            "invoke.completed",
            invocation_id=str(invocation.id),
            duration_ms=result.duration_ms,
        )

        return InvokeResponse(
            invocation_id=invocation.id,
            status=InvocationStatus.completed,
            output=result.output,
            duration_ms=result.duration_ms,
            price_cents=agent.price_per_call_cents,
        )

    return router


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _parse_uuid(value: str, field_name: str) -> UUID:
    """Parse a UUID string, raising ValidationError on failure."""
    try:
        return UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValidationError(
            message=f"Invalid UUID for {field_name}: {value}",
        ) from exc


async def _resolve_agent(
    session: AsyncSession,
    agent_id: UUID | None,
    agent_slug: str | None,
) -> Agent:
    """Look up an agent by id or slug. Raises NotFoundError if missing."""
    if agent_id is None and agent_slug is None:
        raise ValidationError(
            message="Either agent_id or agent_slug must be provided",
        )

    conditions = []
    if agent_id is not None:
        conditions.append(Agent.id == agent_id)
    if agent_slug is not None:
        conditions.append(Agent.slug == agent_slug)

    stmt = select(Agent).where(or_(*conditions))
    result = await session.execute(stmt)
    agent = result.scalar_one_or_none()

    if agent is None:
        identifier = str(agent_id) if agent_id else agent_slug
        raise NotFoundError(
            message=f"Agent not found: {identifier}",
        )

    if agent.status != "active":
        raise ValidationError(
            message=f"Agent is not active (status={agent.status})",
            details={"agent_id": str(agent.id)},
        )

    return agent


def _validate_input(input_data: dict, input_schema: dict) -> None:
    """Validate invocation input against the agent's declared input_schema.

    This is a lightweight check.  If the schema has a ``required`` list, we
    verify that all required keys are present in the input.  If the schema
    has a ``properties`` dict, we verify that all input keys are declared.
    """
    if not input_schema:
        return  # No schema declared — accept anything.

    required = input_schema.get("required", [])
    properties = input_schema.get("properties", {})

    missing = [key for key in required if key not in input_data]
    if missing:
        raise ValidationError(
            message=f"Missing required input fields: {', '.join(missing)}",
            details={"missing_fields": missing},
        )

    if properties:
        unexpected = [key for key in input_data if key not in properties]
        if unexpected:
            raise ValidationError(
                message=f"Unexpected input fields: {', '.join(unexpected)}",
                details={"unexpected_fields": unexpected},
            )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Billing helpers
# --------------------------------------------------------------------------- #


async def _place_hold(
    consumer_id: UUID,
    amount_cents: int,
    invocation_id: UUID,
) -> UUID:
    """Call the billing service to place a funds hold.

    Returns the hold id on success. Raises InsufficientFundsError or
    AgentGateError on failure.
    """
    assert http_client is not None, "HTTP client not initialized"

    url = f"{settings.billing_url}/internal/holds"
    payload = {
        "consumer_account_id": str(consumer_id),
        "amount_cents": amount_cents,
        "invocation_id": str(invocation_id),
    }

    log.debug("billing.place_hold", url=url, payload=payload)

    try:
        resp = await http_client.post(url, json=payload)
    except httpx.HTTPError as exc:
        log.error("billing.hold.request_failed", error=str(exc))
        raise AgentGateError(
            message="Failed to communicate with billing service",
        ) from exc

    if resp.status_code == 402:
        raise InsufficientFundsError(
            message="Insufficient funds to invoke this agent",
            details={"required_cents": amount_cents},
        )

    if resp.status_code >= 400:
        log.error(
            "billing.hold.error",
            status=resp.status_code,
            body=resp.text[:500],
        )
        raise AgentGateError(
            message=f"Billing service error (status {resp.status_code})",
        )

    data = resp.json()
    return UUID(data["id"])


async def _settle_hold(hold_id: UUID, developer_account_id: UUID) -> None:
    """Settle a billing hold after successful agent execution."""
    assert http_client is not None, "HTTP client not initialized"

    url = f"{settings.billing_url}/internal/holds/{hold_id}/settle"
    payload = {"developer_account_id": str(developer_account_id)}

    try:
        resp = await http_client.post(url, json=payload)
        if resp.status_code >= 400:
            log.error(
                "billing.settle.error",
                hold_id=str(hold_id),
                status=resp.status_code,
                body=resp.text[:500],
            )
    except httpx.HTTPError as exc:
        # Settlement failure is non-blocking — the hold will eventually
        # expire and be auto-released by the billing service.
        log.error(
            "billing.settle.request_failed",
            hold_id=str(hold_id),
            error=str(exc),
        )


async def _release_hold(hold_id: UUID) -> None:
    """Release a billing hold after failed/timed-out agent execution."""
    assert http_client is not None, "HTTP client not initialized"

    url = f"{settings.billing_url}/internal/holds/{hold_id}/release"

    try:
        resp = await http_client.post(url)
        if resp.status_code >= 400:
            log.error(
                "billing.release.error",
                hold_id=str(hold_id),
                status=resp.status_code,
                body=resp.text[:500],
            )
    except httpx.HTTPError as exc:
        log.error(
            "billing.release.request_failed",
            hold_id=str(hold_id),
            error=str(exc),
        )


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #

app = create_app()

if __name__ == "__main__":
    uvicorn.run("orchestrator.main:app", host="0.0.0.0", port=8003, reload=True)
