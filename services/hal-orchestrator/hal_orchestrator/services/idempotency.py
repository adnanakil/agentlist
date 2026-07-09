"""Inbound bridge idempotency."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalInboundEvent


def payload_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def internal_message_id(kind: str, silo: str, prompt: str) -> str:
    digest = hashlib.sha256(f"{kind}\n{silo}\n{prompt}".encode()).hexdigest()[:32]
    return f"internal:{kind}:{digest}"


async def begin(
    session: AsyncSession,
    *,
    message_id: str | None,
    silo: str,
    payload: dict,
) -> dict | None:
    """Claim an inbound id, or return its completed response.

    Returns ``None`` to execute the turn. A completed duplicate returns the
    stored response. A concurrent duplicate gets 409 and should retry later.
    """
    if not message_id:
        return None
    digest = payload_hash(payload)
    inserted = (
        await session.execute(
            insert(HalInboundEvent)
            .values(
                id=message_id,
                silo=silo,
                payload_hash=digest,
                status="processing",
            )
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(HalInboundEvent.id)
        )
    ).scalar_one_or_none()
    await session.commit()
    if inserted:
        return None

    event = (
        await session.execute(
            select(HalInboundEvent).where(HalInboundEvent.id == message_id)
        )
    ).scalar_one()
    if event.payload_hash != digest or event.silo != silo:
        raise HTTPException(status_code=409, detail="message_id reused with different payload")
    if event.status == "completed" and isinstance(event.response, dict):
        # Rollback expires ORM attributes. Copy the JSON before closing this
        # read transaction so returning it cannot trigger async lazy loading.
        stored_response = dict(event.response)
        await session.rollback()
        return stored_response
    # Never auto-take over an abandoned action. The prior worker may have
    # completed an irreversible external side effect just before crashing.
    # A new user message gets a new id; stale events are reconciled explicitly.
    await session.rollback()
    raise HTTPException(
        status_code=409,
        detail="message is already processing",
        headers={"Retry-After": "2"},
    )


async def complete(
    session: AsyncSession, message_id: str | None, response: dict
) -> None:
    if not message_id:
        return
    await session.execute(
        update(HalInboundEvent)
        .where(HalInboundEvent.id == message_id)
        .values(
            status="completed",
            response=response,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
