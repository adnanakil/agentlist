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

I've ALREADY pulled the current time and the user's upcoming calendar for you \
(see "Gathered for you" below). Reason over THAT plus the recent conversation \
— don't re-fetch the time or calendar, and don't just relist their schedule.

Your job: is the user about to do something, go somewhere, or expecting \
something in the next ~2 hours (from the calendar below or something they \
mentioned in chat)? If YES — and ONLY then — check whether the real world \
still cooperates in a way they likely don't know yet:
- A departure / outing / reservation coming up → travel_time from their home \
base (live traffic; walking if close) + get_weather for that time. Do they \
need to leave earlier, bring an umbrella, change plans?
- Something they're waiting on (a package, a reservation confirmation, an \
on-sale time, a reply from a specific person they mentioned) → google_gmail \
for a NEW matching email. NOT machine/service notifications (deploys, CI, \
monitoring, app emails) — never relay those.
- An outdoor plan → get_weather for rain/extremes around that time.

Text the user ONLY if you found something genuinely actionable they likely \
don't know yet (leave 15 min early — traffic; rain right when they planned to \
be out; the package just arrived). ONE short message, lead with the thing.

Never alert about baby feed/nap/bedtime timing — the baby system handles that. \
Before claiming an absence ("no reply yet"), verify it against the actual \
emails/events — never assert something you didn't check. Don't repeat an alert \
you already sent (check your own recent messages).

Otherwise reply with EXACTLY "..." — nothing imminent in the next ~2h, \
conditions fine, nothing new, or you already told them. Most heartbeats MUST \
be silent. Never use a heartbeat to ask a question, request Google access, \
make small talk, or report tool problems."""


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


async def _gather_context(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient, silo: str
) -> str:
    """Pre-fetch the facts the heartbeat must reason over — current time +
    upcoming calendar — so the cheap background model doesn't have to *decide*
    to call them. (flash-LOW won't, which made every heartbeat a 0-tool no-op.)
    The model is then handed real anticipation material and only has to check
    weather/traffic/email for whatever's actually coming up."""
    from hal_orchestrator.tools.registry import ToolContext, execute_tool

    lines: list[str] = []
    async for session in db_session.get_session():
        ctx = ToolContext(phone=silo, session=session, settings=settings, http_client=http)
        try:
            lines.append("Current time — " + str(await execute_tool("current_time", {}, ctx)))
        except Exception:
            log.exception("heartbeat.gather_time_failed", silo=silo)
        try:
            cal = str(await execute_tool("google_calendar", {"action": "list_events"}, ctx))
            lines.append("Upcoming calendar:\n" + cal)
        except Exception:
            log.exception("heartbeat.gather_cal_failed", silo=silo)
        break
    return "\n\n".join(lines)


async def _beat(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient, silo: str
) -> None:
    """One internal agent turn; deliver the reply (if any) via the outbox."""
    import hal_orchestrator.state as state
    from hal_orchestrator.services.identity import is_group_id

    port = os.environ.get("PORT", "8005")
    is_group = is_group_id(silo)

    # Hand the model real anticipation material up front (the cheap model won't
    # go fetch it on its own).
    prompt = HEARTBEAT_PROMPT
    context = await _gather_context(settings, http, silo)
    if context:
        prompt += "\n\n## Gathered for you (reason over this — don't re-fetch):\n" + context

    payload: dict = {
        "phone": silo,
        "text": prompt,
        "is_group": is_group,
        "internal": True,
        # Cheap background model, but MEDIUM (not LOW) thinking: LOW one-shot
        # "..." with zero tool calls, defeating the whole check. With the facts
        # pre-gathered, MEDIUM only has to reason + check weather/traffic.
        "model": settings.gemini_background_model,
        "thinking_level": "MEDIUM",
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
