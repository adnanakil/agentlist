"""STOP / opt-out — "when someone says stop, we actually stop."

Deterministic, route-level, never model-mediated (same contract as
services/forget.py). A 1:1 user whose whole message is a stop keyword gets one
confirmation reply and a ``stopped_at`` marker on their profile. From then on:

- the message route answers nothing except START (resume) or the forget-me /
  delete-me flow (privacy must always stay reachable), and
- ``delivery.enqueue`` refuses every outbound message to them, which covers
  ALL proactive producers (reminders, cron, heartbeat, follow-ups, first-win,
  billing, growth, watches) at the single choke point they share.

Keyword choices: "stop" and its unambiguous variants are honored. Bare
"cancel" / "end" / "quit" are deliberately NOT keywords — in a conversational
assistant those collide with normal replies ("cancel" to a reminder offer,
"quit" in a game) and HAL's primary transports are iMessage/WhatsApp, not
carrier A2P SMS. Explicit sentences ("stop texting me") are honored.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalOutboxMessage, HalUserProfile

log = structlog.get_logger()

# Whole-message matches only, after normalize(). Order/formatting free.
STOP_PHRASES = frozenset(
    {
        "stop",
        "stopall",
        "stop all",
        "unsubscribe",
        "opt out",
        "optout",
        "stop texting me",
        "stop messaging me",
        "stop texting",
        "stop messaging",
        "don't text me",
        "dont text me",
        "do not text me",
        "don't message me",
        "dont message me",
        "do not message me",
    }
)

# Only consulted while stopped, so conversational collisions ("start" as an
# answer to "ready?") can't fire by accident.
START_PHRASES = frozenset(
    {"start", "unstop", "resume", "subscribe", "opt in", "optin", "start again"}
)

# Arms the C3 forget-me two-step in routes/message.py ("delete everything"
# within 48h executes). "delete me" and friends are aliases for "forget me".
FORGET_PHRASES = frozenset(
    {
        "forget me",
        "/forget",
        "delete me",
        "/delete",
        "delete my data",
        "delete my account",
        "delete my info",
        "delete my information",
    }
)


def normalize(text: str) -> str:
    """One whole-message form: trimmed, lowercased, trailing punctuation gone
    ("STOP!!", " Delete Me. " and "stop" all normalize identically)."""
    return (text or "").strip().lower().rstrip(".!?…,").strip()


async def is_stopped(session: AsyncSession, silo: str) -> bool:
    """True if this silo has an active STOP opt-out marker."""
    if not silo:
        return False
    val = (
        await session.execute(
            select(HalUserProfile.extra_data["stopped_at"].astext).where(
                HalUserProfile.phone == silo
            )
        )
    ).scalar_one_or_none()
    return bool(val)


async def mark_stopped(session: AsyncSession, silo: str) -> int:
    """Set the opt-out marker and purge any queued-but-unsent messages to this
    silo, so nothing already in the outbox lands after the STOP. Returns the
    number of purged deliveries. The caller commits."""
    from hal_orchestrator.services.profiles import update_profile

    await update_profile(session, silo, stopped_at=datetime.now(UTC).isoformat())
    result = await session.execute(
        sa_delete(HalOutboxMessage).where(
            HalOutboxMessage.destination == silo,
            HalOutboxMessage.status.in_(("pending", "leased")),
        )
    )
    purged = int(result.rowcount or 0)
    log.info("optout.stopped", silo=silo, purged_outbox=purged)
    return purged


async def clear_stopped(session: AsyncSession, silo: str) -> None:
    """Lift the opt-out (user texted START). The caller commits."""
    from hal_orchestrator.services.profiles import update_profile

    await update_profile(session, silo, stopped_at=None)
    log.info("optout.resumed", silo=silo)
