"""Heartbeat — per-silo anticipation checks.

The abstraction: every ~15 minutes per recently-active silo, HAL quietly asks
"is this user about to do something or expecting something soon — and could
the world have changed under it?" (a reservation coming up → check weather /
travel time with live traffic; an expected delivery → check email). It texts
ONLY when it finds something actionable; the overwhelming default is silence.

Mechanics: an internal full agent turn through /api/message (internal=true),
so the check gets the silo's real context — profile, memories, conversation,
playbook — and every tool. Silent checks persist nothing (see message.py);
alerts persist a compact stub and are graded by the nightly growth loop, so
bad alerts surface as bad_judgment and tune future behavior via the playbook.

State is in-memory (last run per silo): a restart just means the next check
runs a little early. No migration needed.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import func, select

from ag_common.config import HalOrchestratorConfig
from ag_db import session as db_session
from ag_db.models import HalTurn

log = structlog.get_logger()

TICK_SECONDS = 60

HEARTBEAT_PROMPT = """\
[HEARTBEAT — automated check-in. The user did NOT text you and will never see \
this prompt; they only see your reply if you send one.]

Quietly consider: is this user about to do something, go somewhere, or \
expecting something in the next ~2 hours? Look at the recent conversation, \
your memory/profile context, and google_calendar (list today's next events). \
Only if something IS coming up, check whether the real world still \
cooperates:
- A departure, outing, or reservation → travel_time from their home base \
(live traffic; consider walking if close) and get_weather. Would they need to \
leave earlier, bring an umbrella, or change plans?
- An expected delivery, confirmation, or reply → google_gmail for a matching \
NEW email since they last mentioned it. Only REAL-WORLD things the user is \
waiting on (a package, a reservation confirmation, an on-sale time, a reply \
from a person). Machine/service notifications — deploy or server alerts, CI, \
monitoring, app emails — are NOT real-world events; never relay those, they \
see them in their own tooling.
- Outdoor plans → get_weather for rain or extremes around that time.

Text the user ONLY if you found something genuinely actionable or worth \
knowing that they likely don't know yet (leave 15 min early — traffic; rain \
right when they planned to walk; the package they were waiting for just got \
delivered). ONE short message, lead with the thing itself.

Never alert about baby feed/nap/bedtime timing — the baby system has its own \
auto-reminders and nudges; a heartbeat repeating them is noise. And before \
claiming something hasn't happened yet ("first feed of the day", "no reply \
yet"), verify against the actual logged events/emails — never assert an \
absence you didn't check.

Otherwise reply with exactly "..." — nothing imminent, conditions fine, \
nothing new, a needed tool/integration isn't available, or you already told \
them (check your own recent messages — never repeat an alert). Most \
heartbeats MUST be silent. Never use a heartbeat to ask the user a question, \
request Google access, make small talk, or report tool problems."""


def in_active_hours(now_local: datetime, settings: HalOrchestratorConfig) -> bool:
    return settings.heartbeat_active_hour_start <= now_local.hour < settings.heartbeat_active_hour_end


def due_silos(
    candidates: list[str],
    last_run: dict[str, datetime],
    now: datetime,
    settings: HalOrchestratorConfig,
) -> list[str]:
    """Filter to silos whose last heartbeat is older than the interval."""
    interval = timedelta(minutes=settings.heartbeat_interval_minutes)
    due = [s for s in candidates if now - last_run.get(s, datetime.min.replace(tzinfo=timezone.utc)) >= interval]
    return due[: settings.heartbeat_max_silos_per_tick]


async def _active_silos(settings: HalOrchestratorConfig) -> list[str]:
    """Silos with a real turn in the activity window. 1:1 only unless groups
    are enabled (group-guarded tools mean group heartbeats see little)."""
    from hal_orchestrator.services.identity import is_group_id
    from hal_orchestrator.services.skills import SHARED_OWNER

    since = datetime.now(timezone.utc) - timedelta(
        hours=settings.heartbeat_activity_window_hours
    )
    async for session in db_session.get_session():
        rows = (
            await session.execute(
                select(HalTurn.phone, func.max(HalTurn.created_at))
                .where(HalTurn.created_at >= since)
                .group_by(HalTurn.phone)
            )
        ).all()
        out = []
        for phone, _ in rows:
            if phone == SHARED_OWNER:
                continue
            if is_group_id(phone) and not settings.heartbeat_include_groups:
                continue
            out.append(phone)
        return sorted(out)
    return []


async def _beat(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient, silo: str
) -> None:
    """One internal agent turn; deliver the reply (if any) via the outbox."""
    import hal_orchestrator.state as state
    from hal_orchestrator.services.identity import is_group_id

    port = os.environ.get("PORT", "8005")
    is_group = is_group_id(silo)
    payload: dict = {
        "phone": silo,
        "text": HEARTBEAT_PROMPT,
        "is_group": is_group,
        "internal": True,
    }
    if is_group:
        payload["chat_id"] = silo

    resp = await http.post(
        f"http://127.0.0.1:{port}/api/message",
        json=payload,
        headers={"Authorization": f"Bearer {settings.hal_bridge_secret}"},
        timeout=300.0,
    )
    resp.raise_for_status()
    data = resp.json()
    reply = (data.get("reply") or "").strip()
    if reply:
        await state.outbox.put({"to": silo, "text": reply})
        log.info("heartbeat.alerted", silo=silo, chars=len(reply))
    for sm in data.get("side_messages", []):
        if sm.get("to") and sm.get("text"):
            await state.outbox.put({"to": sm["to"], "text": sm["text"]})


async def heartbeat_loop(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    if not settings.heartbeat_enabled:
        return
    from hal_orchestrator.prompts.system import USER_TZ

    while db_session._session_factory is None:
        await asyncio.sleep(1)

    log.info(
        "heartbeat.started",
        interval_min=settings.heartbeat_interval_minutes,
        hours=f"{settings.heartbeat_active_hour_start}-{settings.heartbeat_active_hour_end}",
    )
    last_run: dict[str, datetime] = {}
    try:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            try:
                if not in_active_hours(datetime.now(USER_TZ), settings):
                    continue
                now = datetime.now(timezone.utc)
                candidates = await _active_silos(settings)
                for silo in due_silos(candidates, last_run, now, settings):
                    last_run[silo] = now
                    try:
                        await _beat(settings, http, silo)
                    except Exception:
                        log.exception("heartbeat.beat_failed", silo=silo)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("heartbeat.tick_error")
    except asyncio.CancelledError:
        log.info("heartbeat.stopped")
        raise
