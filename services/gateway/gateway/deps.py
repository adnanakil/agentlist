"""FastAPI dependency functions for the gateway service."""

from collections.abc import AsyncGenerator
from typing import Annotated

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.auth import hash_api_key
from ag_common.errors import AuthenticationError
from ag_common.models import AccountRole, AuthenticatedAccount
from ag_db.models import Account, ApiKey
from ag_db.session import get_session

from gateway.config import settings

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module-level singletons (initialized lazily)
# ---------------------------------------------------------------------------
_redis_client: aioredis.Redis | None = None
_http_client: httpx.AsyncClient | None = None


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session."""
    async for session in get_session():
        yield session


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
async def get_current_account(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedAccount:
    """Extract and validate Bearer token from the Authorization header.

    Hashes the presented key, looks it up in the api_keys table, and returns
    an AuthenticatedAccount if valid. Raises 401 otherwise.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthenticationError("Missing or malformed Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise AuthenticationError("Empty API key")

    key_hash = hash_api_key(token)

    stmt = (
        select(ApiKey, Account)
        .join(Account, ApiKey.account_id == Account.id)
        .where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
    )
    result = await db.execute(stmt)
    row = result.first()

    if row is None:
        raise AuthenticationError("Invalid API key")

    api_key: ApiKey = row[0]
    account: Account = row[1]

    if not account.is_active:
        raise AuthenticationError("Account is deactivated")

    # Update last_used_at timestamp (fire-and-forget, best-effort)
    from datetime import datetime, timezone

    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    logger.debug("authenticated", account_id=str(account.id), key_prefix=api_key.key_prefix)

    return AuthenticatedAccount(
        account_id=account.id,
        email=account.email,
        role=AccountRole(account.role),
    )


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
async def get_redis() -> aioredis.Redis:
    """Return a shared Redis async client, creating it on first call."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    """Gracefully close the Redis client."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


# ---------------------------------------------------------------------------
# HTTP client (for inter-service calls)
# ---------------------------------------------------------------------------
async def get_http_client() -> httpx.AsyncClient:
    """Return a shared httpx.AsyncClient, creating it on first call."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    return _http_client


async def close_http_client() -> None:
    """Gracefully close the HTTP client."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
