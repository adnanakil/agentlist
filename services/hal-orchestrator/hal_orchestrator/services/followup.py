"""Post-event follow-up sweep — close the loop on plans HAL helped make.

Every proactive path used to look only at NOW or the FUTURE (heartbeat scans
~2h ahead; reminders/cron fire at preset times). Nothing ever looked BACK: HAL
planned a lunch down to the minute on 2026-06-30, then never asked how it went
and never offered a next one. This daemon is that missing backward glance.

Two phases per event, both model-gated and silent-by-default:
  checkin — a few hours to a couple days after an event HAL helped plan, one
            short "how was it?" (skipped if the chat already debriefed).
  suggest — a few days later, one light "want to do something like it again?"
            with concrete nearby options (the draft turn may use places /
            web_search).

Pipeline per silo: SCAN (cheap model reads the recent archive and lists
HAL-planned events that already happened) → deterministic filters (windows,
dedup via hal_followups, mute check, daily cap, quiet hours) → DRAFT (a full
internal agent turn through /api/message, same as heartbeat, so the silo's
whole context + persona + restraint gates apply; "..." = stay silent) →
deliver via outbox + record a HalFollowup row (recorded even when the draft
chose silence, so an event is never re-litigated).

DISABLED BY DEFAULT (settings.followup_enabled) so a deploy never starts
texting people until the behavior has been reviewed via the dry-run.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import HalOrchestratorConfig
from ag_db import session as db_session
from ag_db.models import HalFollowup, HalMessage, HalTurn

from hal_orchestrator.prompts.system import USER_TZ, resolve_tz
from hal_orchestrator.services.heartbeat import in_active_hours

log = structlog.get_logger()

TICK_SECONDS = 120

# An event must be over this long before a check-in (don't ping mid-dessert)…
CHECKIN_MIN_HOURS = 3.0
# …and no older than this (a check-in 5 days late is worse than none).
CHECKIN_MAX_DAYS = 2.5
# The "do it again?" window.
SUGGEST_MIN_DAYS = 2.5
SUGGEST_MAX_DAYS = 8.0
# At most one follow-up message per silo per this many hours.
SILO_COOLDOWN_HOURS = 20.0
# How much archive the scanner reads. Must comfortably exceed
# SUGGEST_MAX_DAYS + planning lead time: the messages that show HAL *planned*
# an event precede the event itself, and an 8-day-old event planned 3 days
# prior needs ~11+ days of context to be recognized at all.
SCAN_MESSAGES = 100
SCAN_LOOKBACK_DAYS = 14


SCAN_SYSTEM = """\
You scan ONE chat's recent messages for CONCRETE plans that HAL (the
assistant in the chat, whose lines are marked role=assistant) helped plan,
coordinate, or confirm — and that have ALREADY HAPPENED.

Count events where HAL materially helped the plan come together in ANY of
these ways: proposed or vetted options, recommended or confirmed the spot
(hours, fit, logistics), worked out timing or travel, set reminders, or
helped coordinate the members — it still counts when a member picked the
final spot, as long as HAL was part of the planning conversation. Do NOT
count: routine recurring things (naps, feeds, daily briefs, standing calls),
plans made entirely without HAL (it was never asked and never contributed),
vague intentions that never got a concrete time/place, or anything still in
the future.

For each such event also judge `followed_up`: true if the chat AFTER the
event already talked about how it went (in any words — a debrief, photos,
"that was fun", HAL already asked). When in doubt set followed_up=true; a
missed follow-up is cheaper than a redundant one.

Output STRICT JSON only:
{"events": [{"summary": "<one line: who did what, where>",
  "ended_at": "<ISO datetime your best estimate of when it ENDED>",
  "followed_up": false}]}
No events → {"events": []}."""


def event_key(summary: str, ended_at: datetime) -> str:
    """Storage key: date + sorted content words of the summary. Guards against
    EXACT re-processing via the unique constraint; reworded rescans of the
    same event are caught by same_event() below, not by key equality. Pure."""
    words = sorted(
        {w for w in re.findall(r"[a-z0-9]+", (summary or "").lower()) if len(w) > 3}
    )[:5]
    return f"{ended_at:%Y-%m-%d}:" + "-".join(words)[:160]


def same_event(summary_a: str, summary_b: str) -> bool:
    """Do two scan summaries describe the same event? The scanner rewords
    between runs ('Adnan and Seth had lunch at Market 57' vs 'Lunch at Market
    57 for Seth and Adnan'), so dedup is word-overlap, not string equality.
    Pure so it's unit-testable."""
    from hal_orchestrator.services.reminders import is_probable_duplicate

    return is_probable_duplicate(summary_a, summary_b, thr=0.4)


def build_checkin_prompt(summary: str, when_local: str) -> str:
    return (
        "[POST-EVENT FOLLOW-UP — automated check. The users did NOT text you "
        "and never see this prompt; they only see your reply if you send "
        "one.]\n\n"
        f"You helped plan this, and it already happened: {summary} "
        f"(around {when_local}). Nobody here has mentioned it since.\n\n"
        "This is a SANCTIONED proactive check-in — the usual stay-quiet rules "
        "for this chat do not apply to this one turn. Asking how something "
        "you helped plan went is warm and expected, the way a friend texts "
        "the morning after; NOT asking reads as indifference.\n\n"
        "Send ONE short, low-key message asking how it went. Match this "
        "chat's energy. One line is plenty; no logistics, no offers, no "
        "feature pitches, at most one emoji.\n\n"
        "Reply with EXACTLY \"...\" ONLY if one of these CLEARLY holds in the "
        "conversation: it already covered how the event went; the plan fell "
        "through; or members told you to stay out of this chat IN GENERAL "
        "('stop chiming in here', an ongoing mute). A 'keep it to yourself' "
        "or 'butt out' said around the event itself meant quiet DURING their "
        "get-together — it does not forbid one brief, friendly 'how was it?' "
        "afterwards; that's you respecting the moment, then caring after. "
        "Otherwise, SEND the check-in — that's the entire point of this "
        "check."
    )


def build_suggest_prompt(summary: str, when_local: str) -> str:
    return (
        "[POST-EVENT FOLLOW-UP — automated check. The users did NOT text you "
        "and never see this prompt; they only see your reply if you send "
        "one.]\n\n"
        f"A few days ago this happened and seemed to go well: {summary} "
        f"({when_local}).\n\n"
        "This is a SANCTIONED proactive turn — the usual stay-quiet rules for "
        "this chat do not apply to it. People who enjoyed a meetup usually "
        "mean to do it again and just never get around to planning; one good "
        "nudge with real options is genuinely helpful.\n\n"
        "Send ONE short, skippable message offering a concrete next idea: a "
        "repeat, or 1-3 specific current options that fit this group (use "
        "places or web_search so the suggestions are REAL — actual names, "
        "current, and include a link when you have one). Anchor to where "
        "these people actually live/meet (check the conversation — don't "
        "suggest a road-trip town they only visited once). Keep it light: "
        "one message, no pressure, no question barrage.\n\n"
        "Reply with EXACTLY \"...\" ONLY if one of these CLEARLY holds: they "
        "already made their next plan; members told you to stay out of this "
        "chat IN GENERAL ('stop chiming in here', an ongoing mute — a 'butt "
        "out' scoped to the event itself expired with the event); or you "
        "already sent a suggestion like this since the event. Otherwise, "
        "SEND it."
    )


# --------------------------------------------------------------------------- #
# Scan
# --------------------------------------------------------------------------- #


async def load_recent_archive(
    session: AsyncSession, silo: str, limit: int = SCAN_MESSAGES
) -> list[dict]:
    """Newest-last [{at, role, text}] from the durable archive (real
    timestamps, unlike the rolling history window)."""
    since = datetime.now(timezone.utc) - timedelta(days=SCAN_LOOKBACK_DAYS)
    rows = (
        await session.execute(
            select(HalMessage)
            .where(HalMessage.phone == silo, HalMessage.created_at >= since)
            .order_by(HalMessage.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "at": r.created_at.isoformat(timespec="minutes"),
            "role": r.role,
            "text": (r.content or "")[:400],
        }
        for r in reversed(rows)
    ]


def parse_scan_reply(raw: str) -> list[dict]:
    """Parse the scanner's JSON into [{summary, ended_at(datetime),
    followed_up}] — malformed entries are dropped, never raised. Pure."""
    from hal_orchestrator.services.growth import parse_json_block

    out: list[dict] = []
    for ev in (parse_json_block(raw or "").get("events") or [])[:6]:
        if not isinstance(ev, dict) or not ev.get("summary"):
            continue
        try:
            ended = datetime.fromisoformat(str(ev.get("ended_at", "")))
        except ValueError:
            continue
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=timezone.utc)
        out.append(
            {
                "summary": str(ev["summary"])[:300],
                "ended_at": ended,
                "followed_up": bool(ev.get("followed_up")),
            }
        )
    return out


async def scan_silo_events(
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
    session: AsyncSession,
    silo: str,
    summary: str = "",
) -> list[dict]:
    """One cheap-model pass over the silo's recent archive → candidate events.
    Read-only (safe for the dry-run)."""
    from hal_orchestrator.services.gemini import call_gemini

    messages = await load_recent_archive(session, silo)
    if len(messages) < 4:
        return []
    payload = {
        "now": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "chat_summary": (summary or "")[:1200],
        "messages": messages,
    }
    resp = await call_gemini(
        http,
        settings,
        [{"role": "user", "parts": [{"text": json.dumps(payload, indent=1)}]}],
        system=SCAN_SYSTEM,
        model=settings.gemini_background_model,
    )
    if not resp:
        return []
    try:
        parts = resp["candidates"][0]["content"].get("parts", [])
    except (KeyError, IndexError):
        return []
    return parse_scan_reply("".join(p.get("text", "") for p in parts if "text" in p))


# --------------------------------------------------------------------------- #
# Phase selection (pure — unit-testable, reused by the dry-run)
# --------------------------------------------------------------------------- #


def pick_phase(
    ended_at: datetime,
    now: datetime,
    have_checkin: bool,
    have_suggest: bool,
) -> str | None:
    """Which follow-up phase (if any) this event is due for right now."""
    age = now - ended_at
    if age < timedelta(hours=CHECKIN_MIN_HOURS):
        return None
    if not have_checkin and age <= timedelta(days=CHECKIN_MAX_DAYS):
        return "checkin"
    if (
        not have_suggest
        and timedelta(days=SUGGEST_MIN_DAYS) <= age <= timedelta(days=SUGGEST_MAX_DAYS)
    ):
        return "suggest"
    return None


# --------------------------------------------------------------------------- #
# Sweep
# --------------------------------------------------------------------------- #


async def _active_silos(settings: HalOrchestratorConfig) -> list[str]:
    """Silos (groups INCLUDED — that's the point) with real turns recently."""
    from sqlalchemy import func

    from hal_orchestrator.services.skills import SHARED_OWNER

    since = datetime.now(timezone.utc) - timedelta(days=SCAN_LOOKBACK_DAYS)
    async for session in db_session.get_session():
        rows = (
            await session.execute(
                select(HalTurn.phone, func.max(HalTurn.created_at))
                .where(HalTurn.created_at >= since)
                .group_by(HalTurn.phone)
            )
        ).all()
        return sorted(p for p, _ in rows if p != SHARED_OWNER)
    return []


async def _existing_phases(
    session: AsyncSession, silo: str, summary: str, event_at: datetime
) -> tuple[bool, bool]:
    """Which phases already ran for this event — matched fuzzily (the scanner
    rewords summaries between runs) among followups within ±36h of it."""
    lo = event_at - timedelta(hours=36)
    hi = event_at + timedelta(hours=36)
    rows = (
        await session.execute(
            select(HalFollowup).where(
                HalFollowup.silo == silo,
                HalFollowup.event_at >= lo,
                HalFollowup.event_at <= hi,
            )
        )
    ).scalars().all()
    matched = [r for r in rows if same_event(summary, r.event_summary)]
    phases = {r.phase for r in matched}
    return ("checkin" in phases), ("suggest" in phases)


async def _recently_followed_up(session: AsyncSession, silo: str) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=SILO_COOLDOWN_HOURS)
    stmt = select(HalFollowup.id).where(
        HalFollowup.silo == silo,
        HalFollowup.sent_at.isnot(None),
        HalFollowup.sent_at >= cutoff,
    )
    return (await session.execute(stmt)).first() is not None


async def _draft_and_send(
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
    silo: str,
    prompt: str,
) -> str:
    """Full internal agent turn (same mechanics as heartbeat._beat); returns
    the delivered reply ('' = model chose silence)."""
    import hal_orchestrator.state as state
    from hal_orchestrator.services.identity import is_group_id

    port = os.environ.get("PORT", "8005")
    is_group = is_group_id(silo)
    payload: dict = {
        "phone": silo,
        "text": prompt,
        "is_group": is_group,
        "internal": True,
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
        log.info("followup.sent", silo=silo, chars=len(reply))
    return reply


async def sweep_silo(
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
    session: AsyncSession,
    silo: str,
) -> int:
    """Scan one silo and send at most ONE due follow-up. Returns sends."""
    from hal_orchestrator.services.conversation import get_summary
    from hal_orchestrator.services.identity import is_group_id
    from hal_orchestrator.services.watched import is_muted

    now = datetime.now(timezone.utc)

    # Respect a butt-out absolutely: a muted group gets no proactive anything.
    if is_group_id(silo) and await is_muted(session, silo):
        return 0
    if await _recently_followed_up(session, silo):
        return 0

    summary = await get_summary(session, silo)
    events = await scan_silo_events(settings, http, session, silo, summary)
    tz = USER_TZ
    if not is_group_id(silo):
        from hal_orchestrator.services.profiles import get_profile

        tz = resolve_tz(await get_profile(session, silo))

    for ev in events:
        if ev["followed_up"]:
            continue
        key = event_key(ev["summary"], ev["ended_at"])
        have_checkin, have_suggest = await _existing_phases(
            session, silo, ev["summary"], ev["ended_at"]
        )
        phase = pick_phase(ev["ended_at"], now, have_checkin, have_suggest)
        if phase is None:
            continue
        when_local = f"{ev['ended_at'].astimezone(tz):%A %b %-d, %-I:%M %p}"
        prompt = (
            build_checkin_prompt(ev["summary"], when_local)
            if phase == "checkin"
            else build_suggest_prompt(ev["summary"], when_local)
        )
        try:
            reply = await _draft_and_send(settings, http, silo, prompt)
        except Exception:
            log.exception("followup.draft_failed", silo=silo, phase=phase)
            continue
        session.add(
            HalFollowup(
                silo=silo,
                event_key=key,
                event_summary=ev["summary"],
                event_at=ev["ended_at"],
                phase=phase,
                sent_at=now if reply else None,
            )
        )
        await session.flush()
        log.info(
            "followup.recorded",
            silo=silo,
            phase=phase,
            sent=bool(reply),
            key=key[:60],
        )
        return 1 if reply else 0
    return 0


async def followup_loop(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    if not settings.followup_enabled:
        log.info("followup.disabled")
        return

    while db_session._session_factory is None:
        await asyncio.sleep(1)
    Session = db_session._session_factory

    log.info("followup.started", interval_min=settings.followup_interval_minutes)
    last_run: dict[str, datetime] = {}
    try:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            try:
                now = datetime.now(timezone.utc)
                interval = timedelta(minutes=settings.followup_interval_minutes)
                for silo in await _active_silos(settings):
                    if now - last_run.get(
                        silo, datetime.min.replace(tzinfo=timezone.utc)
                    ) < interval:
                        continue
                    # Quiet hours in the silo's own timezone (heartbeat rule).
                    async with Session() as session:
                        tz = USER_TZ
                        from hal_orchestrator.services.identity import is_group_id

                        if not is_group_id(silo):
                            from hal_orchestrator.services.profiles import get_profile

                            tz = resolve_tz(await get_profile(session, silo))
                        if not in_active_hours(datetime.now(tz), settings):
                            continue
                        last_run[silo] = now
                        try:
                            await sweep_silo(settings, http, session, silo)
                            await session.commit()
                        except Exception:
                            log.exception("followup.sweep_failed", silo=silo)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("followup.tick_error")
    except asyncio.CancelledError:
        log.info("followup.stopped")
        raise
