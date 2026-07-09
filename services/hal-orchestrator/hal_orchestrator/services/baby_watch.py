"""Nap-cap watcher — unprompted nudge when a logged nap runs long.

Every check interval: for each family, if the most recent sleep-relevant event
is a daytime nap_start older than the family's nap cap (default 2h) with no
wake logged, queue one nudge to the silo that logged it. One nudge per nap
(tracked in family.state), daytime hours only, and never for night sleep.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import structlog
from sqlalchemy import select

from ag_common.config import HalOrchestratorConfig
from ag_db.models import HalBabyEvent, HalFamily
from ag_db.session import get_session

from hal_orchestrator.services.baby import DEFAULT_SETTINGS, fmt_duration

log = structlog.get_logger()

CHECK_INTERVAL_SECONDS = 120
NUDGE_HOURS = (7, 20)  # local hours within which nudges may fire


async def baby_watch_loop(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    log.info("baby_watch.started")
    while True:
        try:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            await _check_naps()
        except asyncio.CancelledError:
            log.info("baby_watch.cancelled")
            raise
        except Exception:
            log.exception("baby_watch.error")
            await asyncio.sleep(10)


async def _check_naps() -> None:
    now = datetime.now(timezone.utc)
    async for session in get_session():
        families = (await session.execute(select(HalFamily))).scalars().all()
        for family in families:
            fam_settings = {**DEFAULT_SETTINGS, **(family.settings or {})}
            cap_min = int(fam_settings.get("nap_cap_minutes") or 0)
            if cap_min <= 0:
                continue

            tz = ZoneInfo(family.timezone)
            local_hour = now.astimezone(tz).hour
            if not (NUDGE_HOURS[0] <= local_hour < NUDGE_HOURS[1]):
                continue

            # Most recent sleep-relevant event decides the current state.
            stmt = (
                select(HalBabyEvent)
                .where(
                    HalBabyEvent.family_id == family.id,
                    HalBabyEvent.kind.in_(["nap_start", "bedtime", "wake"]),
                )
                .order_by(HalBabyEvent.event_at.desc())
                .limit(1)
            )
            last = (await session.execute(stmt)).scalar_one_or_none()
            if last is None or last.kind != "nap_start":
                continue

            elapsed = now - last.event_at
            # Nudge only inside [cap, cap+60min] — beyond that the wake was
            # almost certainly just not logged, and a late nudge is noise.
            if elapsed < timedelta(minutes=cap_min) or elapsed > timedelta(
                minutes=cap_min + 60
            ):
                continue

            if (family.state or {}).get("nap_nudge_event_id") == str(last.id):
                continue  # already nudged for this nap
            if not last.silo:
                continue  # no delivery target (e.g. backfilled event)

            text = (
                f"⏰ {family.baby_name}'s been napping {fmt_duration(int(elapsed.total_seconds() // 60))} "
                f"(down at {last.event_at.astimezone(tz).strftime('%-I:%M %p')}) — past the "
                f"{fmt_duration(cap_min)} cap. Might be time to wake him so bedtime stays on "
                f"track. If he already woke, just tell me when."
            )
            from hal_orchestrator.services.delivery import enqueue

            await enqueue(
                session,
                to=last.silo,
                text=text,
                idempotency_key=f"baby-nap-cap:{last.id}",
            )
            family.state = {**(family.state or {}), "nap_nudge_event_id": str(last.id)}
            await session.flush()
            log.info(
                "baby_watch.nudged",
                family=str(family.id),
                to=last.silo,
                elapsed_min=int(elapsed.total_seconds() // 60),
            )
        await session.commit()
