"""Group observations — the one-way valve from group chats to personal silos.

Direction of flow (enforced here and at the call sites):
  WRITE: only the group-side enricher calls add_observations(), and only for
         handles that actually appear as senders in that group's transcript
         (the membership guard — we can't enumerate a chat's roster, so
         "spoke in the chat" is the proxy for "is in the chat").
  READ:  only recent_for_member(), called when building a 1:1 turn's context.
         Group turns never read this table, so nothing personal can round-trip
         into a group.

Observations are time-relevant ("planning X this weekend"), so reads age them
out and writes prune per (member, group) to keep the store small.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalGroupObservation

log = structlog.get_logger()

MAX_PER_MEMBER_GROUP = 10
MAX_OBSERVATION_CHARS = 300
READ_MAX_AGE_DAYS = 14
READ_LIMIT = 12

# Sender prefixes as they appear in stored group history: "[+12017570419]: hi"
PARTICIPANT_RX = re.compile(r"\[(\+\d{7,15})\]")


def extract_participants(transcript: str) -> set[str]:
    """Handles that actually spoke in this transcript — the membership guard."""
    return set(PARTICIPANT_RX.findall(transcript or ""))


async def add_observations(
    session: AsyncSession,
    group_silo: str,
    group_name: str,
    items: list[dict],
    participants: set[str],
) -> int:
    """Store observations for members; silently drop any for handles that
    didn't speak in the transcript. Returns how many were written."""
    from hal_orchestrator.services.identity import normalize_handle

    written = 0
    touched: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        handle = normalize_handle(str(item.get("handle") or ""))
        content = str(item.get("observation") or "").strip()[:MAX_OBSERVATION_CHARS]
        if not handle or not content:
            continue
        if handle not in participants:
            log.warning(
                "group_obs.non_participant_dropped",
                group=group_silo,
                handle=handle,
            )
            continue
        session.add(
            HalGroupObservation(
                member_phone=handle,
                group_silo=group_silo,
                group_name=(group_name or "")[:255],
                content=content,
            )
        )
        written += 1
        touched.add(handle)

    # Prune: keep only the newest MAX_PER_MEMBER_GROUP per (member, group).
    await session.flush()
    for handle in touched:
        ids = (
            await session.execute(
                select(HalGroupObservation.id)
                .where(
                    HalGroupObservation.member_phone == handle,
                    HalGroupObservation.group_silo == group_silo,
                )
                .order_by(HalGroupObservation.created_at.desc())
                .offset(MAX_PER_MEMBER_GROUP)
            )
        ).scalars().all()
        if ids:
            await session.execute(
                delete(HalGroupObservation).where(HalGroupObservation.id.in_(ids))
            )
    return written


async def recent_for_member(
    session: AsyncSession, phone: str
) -> list[HalGroupObservation]:
    """Fresh observations for ONE member, newest first. 1:1 context only —
    never call this from a group turn."""
    since = datetime.now(timezone.utc) - timedelta(days=READ_MAX_AGE_DAYS)
    rows = (
        await session.execute(
            select(HalGroupObservation)
            .where(
                HalGroupObservation.member_phone == phone,
                HalGroupObservation.created_at >= since,
            )
            .order_by(HalGroupObservation.created_at.desc())
            .limit(READ_LIMIT)
        )
    ).scalars().all()
    return list(rows)
