"""Helpful mode — an OPT-IN proactive concierge.

Where the heartbeat is silent-by-default *anticipation* ("is a plan about to go
sideways?"), helpful mode is a chosen, low-frequency *concierge*. Once a day it
sends a short brief tailored to the user's SITUATION (profile + recalled
memories — on leave, a baby at home) and LOCATION (weather, local events, local
news, today's agenda). It may also send a few capped same-day pings when
something genuinely changes (rain moving in, a standout event tonight).

Per-user opt-in + daily caps live in profile.extra_data["helpful"]:
  enabled    : bool                — master per-user switch
  interests  : list[str]           — subset of weather|events|news|agenda
  hour       : int                 — local hour for the daily brief (default 8)
  last_brief : "YYYY-MM-DD" (local)— date the brief last fired (once/day)
  pings      : int                 — opportunistic pings sent today
  pings_date : "YYYY-MM-DD" (local)— day the ping counter belongs to
  last_check : ISO utc             — last opportunistic check (spacing gate)

Like the heartbeat it runs an internal /api/message turn (internal=true), so the
turn inherits the silo's real profile, memories, conversation and every tool —
the situation/location awareness comes for free from that path.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import structlog
from sqlalchemy import select

from ag_common.config import HalOrchestratorConfig
from ag_db import session as db_session
from ag_db.models import HalUserProfile

log = structlog.get_logger()

DEFAULT_INTERESTS = ["weather", "events", "news", "agenda"]

BRIEF_PROMPT = """\
[HELPFUL MODE — automated daily brief. The user OPTED IN to a proactive morning \
brief. They did NOT text you and won't see this prompt; they only see what you \
send. Send ONE short, warm iMessage — no "let me know if…" filler, no question \
at the end.]

You've been handed the current time, today's weather, today's calendar, and \
recent unread email below (see "Gathered for you"). You also know the user's \
SITUATION and LOCATION from their profile and your memories (e.g. on leave, a \
baby at home, where they live) — TAILOR everything to it.

Build a brief that's genuinely useful for THEIR specific day, drawing on the \
interests they enabled: {interests}. Use web_search for anything live you don't \
already have — local events / things to do today, a notable local or topic \
headline. Pick the 2–4 things that actually matter today and skip the rest; do \
NOT pad with empty sections.

Shape (adapt freely, ~3–6 short plain-text lines, lead with the most useful thing):
- Weather: today's outlook + any window that matters (a dry spell good for a \
walk, rain to plan around).
- Today: anything real on the calendar or a genuinely time-sensitive email; if \
the day's open, say so in a few words.
- One or two ideas TAILORED to their situation + location — e.g. on leave with a \
baby: a stroller-friendly walk, a nearby park or library storytime, a good \
errand window. Specific and local, never generic filler.
- Optionally ONE headline (local, or a topic they follow) only if it's notable.

Never invent: no weather if you couldn't get it, no event/headline web_search \
didn't actually return. Before citing a specific email, read its FULL body \
(google_gmail action=read_email with its id) and state the concrete cause/fix \
it actually contains — never characterize an email from its subject alone. \
Warm, concise, specific."""

PING_PROMPT = """\
[HELPFUL MODE — same-day check. The user opted into occasional proactive pings. \
They did NOT text you. The bar is HIGH: send ONLY if something has CHANGED since \
this morning that's genuinely worth interrupting them for RIGHT NOW — otherwise \
stay silent. Most checks MUST be silent.]

You've been handed the current time, latest weather, calendar, and recent unread \
email below. Is there a NEW, time-sensitive, useful thing vs a normal day? \
Examples worth a ping: rain/a storm moving in within a few hours when they may \
be out; a standout local event happening TONIGHT they'd want to catch; a notable \
local or topic news development; a genuinely time-sensitive email. Use web_search \
only to confirm a specific live thing. TAILOR to their situation + location.

If something clears that bar: ONE short message, lead with the thing, no \
question. Before pinging about a specific email, read its FULL body \
(google_gmail action=read_email) and lead with the concrete cause and fix it \
actually states — never a vague "action needed on your account". Do NOT repeat \
the morning brief or anything you already sent today (check your recent \
messages). If nothing clears it — and usually nothing does — reply with \
EXACTLY "..." and nothing else. Never ping to check in or make small talk."""


# get_weather emits "(~NN%)" only for an actual upcoming rain window (the "dry"
# line has no percentage). Detecting it lets us push past the ping's strong
# silence default on the one high-value opportunistic trigger we can see in the
# pre-fetched context — same deterministic-directive trick as the heartbeat's
# delivery fix (the cheap model flip-flops on borderline "should I interrupt?").
_RAIN_WINDOW_RE = re.compile(r"\(~\s*\d{1,3}\s*%\)")


def precip_directive(gathered: str) -> str:
    """A firm flag directive when the weather block shows a rain window; ''
    otherwise. Only applied to opportunistic PINGS (the brief always covers
    weather anyway). The model still decides today-vs-later and dedups."""
    if not _RAIN_WINDOW_RE.search(gathered or ""):
        return ""
    return (
        "‼️ The weather above shows a RAIN WINDOW. If it lands TODAY and they "
        "might be out (a stroller walk, errands), that's a worth-it heads-up: "
        "say WHEN the rain hits and one quick tailored tweak (get the walk in "
        "before it / a cozy indoor idea), UNLESS you already told them today. "
        "If the rain is not today, stay silent."
    )


def _helpful_state(profile: HalUserProfile) -> dict | None:
    hp = (profile.extra_data or {}).get("helpful")
    return hp if isinstance(hp, dict) and hp.get("enabled") else None


def _save_state(profile: HalUserProfile, hp: dict) -> None:
    """Reassign extra_data wholesale so SQLAlchemy sees the JSONB change."""
    merged = dict(profile.extra_data or {})
    merged["helpful"] = hp
    profile.extra_data = merged


async def _gather(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient, silo: str, location: str
) -> str:
    """Pre-fetch what the brief reasons over — time, today's weather, calendar,
    recent unread email — so the cheap background model doesn't have to decide to
    call them (events/news it still fetches via web_search)."""
    from hal_orchestrator.tools.registry import ToolContext, execute_tool

    lines: list[str] = []
    plan: list[tuple[str, str, dict]] = [("Current time", "current_time", {})]
    if location:
        # No hard-coded city fallback: a non-NYC user with an unset
        # home_location was getting a "local" brief built on NYC weather.
        # Unknown location -> skip weather; the model can ask for home_location.
        plan.append(("Today's weather", "get_weather", {"location": location}))
    else:
        lines.append(
            "Today's weather — (skipped: the user's home_location isn't saved; "
            "if the brief would benefit, ask for it once and save it to the "
            "profile rather than assuming a city)"
        )
    plan += [
        ("Today's calendar", "google_calendar", {"action": "list_events"}),
        (
            "Recent unread email",
            "google_gmail",
            {"action": "list_emails", "query": "is:unread newer_than:1d", "max_results": 6},
        ),
    ]
    async for session in db_session.get_session():
        ctx = ToolContext(phone=silo, session=session, settings=settings, http_client=http)
        for label, name, args in plan:
            try:
                lines.append(f"{label} — " + str(await execute_tool(name, args, ctx)))
            except Exception:
                log.exception("helpful.gather_failed", silo=silo, tool=name)
        break
    return "\n\n".join(lines)


async def _fire(
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
    silo: str,
    *,
    mode: str,
    interests: list[str],
    location: str,
) -> str:
    """One internal helpful turn. Returns the reply ('' = stayed silent)."""
    base = (
        BRIEF_PROMPT.format(interests=", ".join(interests))
        if mode == "brief"
        else PING_PROMPT
    )
    gathered = await _gather(settings, http, silo, location)
    prompt = base + "\n\n## Gathered for you (reason over this — don't re-fetch):\n" + gathered
    if mode == "ping":
        directive = precip_directive(gathered)
        if directive:
            prompt += "\n\n" + directive

    port = os.environ.get("PORT", "8005")
    resp = await http.post(
        f"http://127.0.0.1:{port}/api/message",
        json={
            "phone": silo,
            "text": prompt,
            "internal": True,
            # The once-a-day brief runs on the MAIN model: it must reliably
            # produce a non-empty message AND actually web_search for live local
            # events/news (the cheap background model returns 0 tool calls and
            # occasionally nothing). Frequent opportunistic pings stay cheap.
            "model": settings.helpful_model or (
                settings.gemini_model if mode == "brief"
                else settings.gemini_background_model
            ),
            "thinking_level": "MEDIUM",
        },
        headers={"Authorization": f"Bearer {settings.hal_bridge_secret}"},
        timeout=300.0,
    )
    resp.raise_for_status()
    return (resp.json().get("reply") or "").strip()


def _is_quiet(text: str) -> bool:
    return text.strip().strip(".…·•- \t\n") == ""


async def _run_once(settings: HalOrchestratorConfig, http: httpx.AsyncClient) -> None:
    """Two phases, deliberately separated: (1) decide + DURABLY claim each slot
    in a SHORT transaction, then (2) fire outside any DB session. Never hold a
    session open across the (~30s) _fire HTTP call — that drops the connection,
    the commit fails, the guard (last_brief) is lost, and the brief re-fires
    every tick. Claiming the slot before firing also means a fire that errors
    just skips today rather than retry-spamming."""
    from hal_orchestrator.prompts.system import USER_TZ

    now = datetime.now(timezone.utc)
    actions: list[tuple[str, str, list, str]] = []  # (silo, mode, interests, location)

    # --- Phase 1: claim slots (no HTTP inside this transaction) ---------------
    async for session in db_session.get_session():
        profiles = (await session.execute(select(HalUserProfile))).scalars().all()
        for profile in profiles:
            hp = _helpful_state(profile)
            if hp is None:
                continue

            extra = profile.extra_data or {}
            tz_name = extra.get("timezone")
            tz = ZoneInfo(tz_name) if tz_name else USER_TZ
            local = now.astimezone(tz)
            today = local.date().isoformat()
            brief_hour = int(hp.get("hour", settings.helpful_brief_hour))
            interests = hp.get("interests") or DEFAULT_INTERESTS
            location = extra.get("home_location") or ""

            new_hp = dict(hp)
            # New local day: reset the opportunistic ping counter.
            if new_hp.get("pings_date") != today:
                new_hp["pings"], new_hp["pings_date"] = 0, today

            mode: str | None = None
            # Daily brief: ONCE, inside a morning window only (never the evening).
            if (
                brief_hour <= local.hour < brief_hour + settings.helpful_brief_window_hours
                and new_hp.get("last_brief") != today
            ):
                new_hp["last_brief"] = today
                mode = "brief"
            # Opportunistic ping: brief done today, under cap, well-spaced.
            elif (
                new_hp.get("last_brief") == today
                and brief_hour <= local.hour < settings.helpful_active_hour_end
                and int(new_hp.get("pings", 0)) < settings.helpful_max_pings_per_day
                and _gap_ok(new_hp.get("last_check"), now, settings.helpful_ping_min_gap_hours)
            ):
                new_hp["last_check"] = now.isoformat()  # spacing gate claimed now
                mode = "ping"

            if new_hp != hp:
                _save_state(profile, new_hp)
            if mode:
                actions.append((profile.phone, mode, interests, location))
        await session.commit()  # guards durable BEFORE any fire

    # --- Phase 2: fire + deliver (outside any DB transaction) -----------------
    for silo, mode, interests, location in actions:
        try:
            reply = await _fire(
                settings, http, silo, mode=mode, interests=interests, location=location
            )
        except Exception:
            log.exception("helpful.fire_failed", silo=silo, mode=mode)
            continue
        if mode == "brief":
            if reply:
                await _deliver(silo, reply)
                log.info("helpful.brief_sent", silo=silo, chars=len(reply))
        elif reply and not _is_quiet(reply):  # ping
            await _deliver(silo, reply)
            await _bump_ping(silo)
            log.info("helpful.ping_sent", silo=silo)


async def _bump_ping(silo: str) -> None:
    """Increment today's ping count in its own short transaction — only after a
    ping actually went out (last_check was already claimed in phase 1)."""
    async for session in db_session.get_session():
        profile = (
            await session.execute(
                select(HalUserProfile).where(HalUserProfile.phone == silo)
            )
        ).scalar_one_or_none()
        if profile is not None:
            hp = dict((profile.extra_data or {}).get("helpful") or {})
            hp["pings"] = int(hp.get("pings", 0)) + 1
            _save_state(profile, hp)
            await session.commit()
        break


def _gap_ok(last_check_iso: str | None, now: datetime, min_gap_hours: int) -> bool:
    if not last_check_iso:
        return True
    try:
        last = datetime.fromisoformat(last_check_iso)
    except ValueError:
        return True
    return now - last >= timedelta(hours=min_gap_hours)


async def _deliver(silo: str, text: str) -> None:
    import hal_orchestrator.state as state

    await state.outbox.put({"to": silo, "text": text})


async def helpful_loop(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    if not settings.helpful_enabled:
        return
    while db_session._session_factory is None:
        await asyncio.sleep(1)
    log.info("helpful.started", interval_s=settings.helpful_check_interval_seconds)
    try:
        while True:
            await asyncio.sleep(settings.helpful_check_interval_seconds)
            try:
                await _run_once(settings, http)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("helpful.tick_error")
    except asyncio.CancelledError:
        log.info("helpful.stopped")
        raise
