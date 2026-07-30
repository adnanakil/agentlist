"""Durable bridge outbox.

Producers may pass their current session to make an outbound message part of the
same transaction as the state change that caused it. The Queue-compatible
facade is retained for older call sites and standalone tests.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

import ag_db.session as db_session
from ag_db.models import HalOutboxMessage, HalSiloChannel

log = structlog.get_logger()

# "test" is the admin test console (routes/testconsole.py): simulated silos
# record it as their transport so every outbox row addressed to them — proactive
# sends included — is claimed by the console, never by a real bridge.
KNOWN_CHANNELS = ("imessage", "whatsapp", "test")


async def channel_of(session: AsyncSession, silo: str) -> str:
    """Transport the silo last spoke on; imessage until proven otherwise."""
    row = await session.get(HalSiloChannel, silo)
    return row.channel if row is not None else "imessage"


async def record_silo_channel(
    session: AsyncSession, silo: str, channel: str
) -> None:
    """Upsert silo -> channel on an inbound user message (last channel wins)."""
    if channel not in KNOWN_CHANNELS or not silo:
        return
    stmt = (
        insert(HalSiloChannel)
        .values(silo=silo, channel=channel)
        .on_conflict_do_update(
            index_elements=["silo"],
            set_={"channel": channel, "updated_at": datetime.now(timezone.utc)},
        )
    )
    await session.execute(stmt)


async def enqueue(
    session: AsyncSession,
    *,
    to: str,
    text: str,
    idempotency_key: str | None = None,
    images: list[dict] | None = None,
    channel: str | None = None,
) -> uuid.UUID | None:
    """Add one delivery to the caller's transaction.

    ``images`` is an optional list of {mime_type, data(base64), ext} the bridge
    sends as file attachments after the text. ``channel`` picks the delivering
    bridge; None resolves from the destination silo's last-seen transport.
    """
    if not to or not text:
        return None
    if not isinstance(session, AsyncSession):
        # Standalone regression harnesses use a minimal fake session. Keep
        # Queue compatibility there; production always passes AsyncSession.
        import hal_orchestrator.state as state

        await state.outbox.put(
            {
                "to": to,
                "text": text,
                "idempotency_key": idempotency_key,
                "images": images or [],
            }
        )
        return None
    if channel is None:
        channel = await channel_of(session, to)
    message_id = uuid.uuid4()
    stmt = (
        insert(HalOutboxMessage)
        .values(
            id=message_id,
            destination=to,
            channel=channel,
            text=text,
            images=images or None,
            idempotency_key=idempotency_key,
            status="pending",
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(HalOutboxMessage.id)
    )
    inserted = (await session.execute(stmt)).scalar_one_or_none()
    return inserted


async def claim(
    session: AsyncSession,
    *,
    limit: int = 100,
    auto_ack: bool = True,
    lease_seconds: int = 90,
    channel: str = "imessage",
) -> list[dict]:
    """Claim pending deliveries with row locks safe across bridge/API replicas.

    ``auto_ack`` preserves the current bridge's drain-on-read protocol. A newer
    bridge can request leases and acknowledge only after AppleScript succeeds.
    Each bridge claims only its own ``channel``.
    """
    now = datetime.now(timezone.utc)
    rows = (
        (
            await session.execute(
                select(HalOutboxMessage)
                .where(
                    HalOutboxMessage.channel == channel,
                    HalOutboxMessage.available_at <= now,
                    or_(
                        HalOutboxMessage.status == "pending",
                        (
                            (HalOutboxMessage.status == "leased")
                            & (HalOutboxMessage.lease_until < now)
                        ),
                    ),
                )
                .order_by(HalOutboxMessage.created_at)
                .limit(max(1, min(limit, 200)))
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    result = []
    for row in rows:
        row.attempts += 1
        if auto_ack:
            row.status = "delivered"
            row.delivered_at = now
            row.lease_until = None
        else:
            row.status = "leased"
            row.lease_until = now + timedelta(seconds=lease_seconds)
        result.append(
            {
                "id": str(row.id),
                "to": row.destination,
                "text": row.text,
                "images": row.images or [],
            }
        )
    await session.flush()
    return result


async def acknowledge(
    session: AsyncSession, message_ids: list[uuid.UUID], *, delivered: bool
) -> int:
    if not message_ids:
        return 0
    now = datetime.now(timezone.utc)
    values = (
        {"status": "delivered", "delivered_at": now, "lease_until": None}
        if delivered
        else {"status": "pending", "available_at": now, "lease_until": None}
    )
    result = await session.execute(
        update(HalOutboxMessage)
        .where(
            HalOutboxMessage.id.in_(message_ids),
            HalOutboxMessage.status.in_(["leased", "pending"]),
        )
        .values(**values)
    )
    return int(result.rowcount or 0)


class DurableOutbox:
    """Queue-compatible facade used by existing producers."""

    def __init__(self) -> None:
        self._startup_fallback: asyncio.Queue[dict] = asyncio.Queue()

    async def put(self, item: dict) -> None:
        factory = db_session._session_factory
        if factory is None:
            await self._startup_fallback.put(item)
            return
        async with factory() as session:
            await enqueue(
                session,
                to=str(item.get("to") or ""),
                text=str(item.get("text") or ""),
                idempotency_key=item.get("idempotency_key"),
                images=item.get("images") or None,
                channel=item.get("channel"),
            )
            await session.commit()

    def empty(self) -> bool:
        return self._startup_fallback.empty()

    def get_nowait(self) -> dict:
        return self._startup_fallback.get_nowait()


outbox = DurableOutbox()
