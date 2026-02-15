"""Redis sliding-window rate limiter implemented as a FastAPI dependency."""

import time

import redis.asyncio as aioredis
import structlog
from fastapi import Depends

from ag_common.errors import RateLimitError
from ag_common.models import AuthenticatedAccount

from gateway.config import settings
from gateway.deps import get_current_account, get_redis

logger = structlog.get_logger()


async def check_rate_limit(
    account: AuthenticatedAccount = Depends(get_current_account),
    redis: aioredis.Redis = Depends(get_redis),
) -> AuthenticatedAccount:
    """Sliding-window rate limiter using a Redis sorted set.

    Key layout:
        rate_limit:{account_id}  — sorted set where each member is a unique
        request identifier and the score is the Unix timestamp (float) of the
        request.

    Algorithm:
        1. Remove all entries older than the window (60 s).
        2. Count remaining entries.
        3. If the count >= configured limit, raise RateLimitError.
        4. Otherwise, add the current request and set TTL on the key.

    Returns the authenticated account so downstream route handlers can
    depend on ``check_rate_limit`` and still receive the account.
    """
    key = f"rate_limit:{account.account_id}"
    now = time.time()
    window_start = now - 60.0  # 1-minute window
    max_requests = settings.rate_limit_per_minute

    pipe = redis.pipeline(transaction=True)

    # 1. Remove entries outside the window
    pipe.zremrangebyscore(key, "-inf", window_start)

    # 2. Count current entries
    pipe.zcard(key)

    # 3. Add the new request (unique member = timestamp with enough precision)
    member = f"{now}"
    pipe.zadd(key, {member: now})

    # 4. Ensure the key expires eventually even without traffic
    pipe.expire(key, 120)

    results = await pipe.execute()
    current_count: int = results[1]  # zcard result

    if current_count >= max_requests:
        # We already added the entry — remove it so the overshoot doesn't persist
        await redis.zrem(key, member)
        logger.warning(
            "rate_limit_exceeded",
            account_id=str(account.account_id),
            count=current_count,
            limit=max_requests,
        )
        raise RateLimitError(
            f"Rate limit exceeded: {max_requests} requests per minute",
            details={"limit": max_requests, "window_seconds": 60},
        )

    return account
