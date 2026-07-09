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
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import structlog
from sqlalchemy import func, select

from ag_common.config import HalOrchestratorConfig
from ag_db import session as db_session
from ag_db.models import HalTurn

from hal_orchestrator.prompts.system import USER_TZ, resolve_tz
from hal_orchestrator.services.idempotency import internal_message_id

log = structlog.get_logger()

TICK_SECONDS = 60

# How long a surfaced-item key stays in the dedup set. Unread mail older than
# 1d falls out of the gather query anyway; 7d covers stubbornly-unread items.
SEEN_TTL_HOURS = 24 * 7

HEARTBEAT_PROMPT = """\
[HEARTBEAT — automated check-in. The user did NOT text you and will never see \
this prompt; they only see your reply if you send one.]

I've ALREADY pulled the current time, the user's upcoming calendar, AND their \
recent unread email for you (see "Gathered for you" below). Reason over THAT \
plus the recent conversation — don't re-list or re-query what's already there. \
ONE exception: before you ALERT about a specific email, call \
google_gmail(action=read_email, message_id=<its id>) and read the FULL body \
first. A subject/snippet is not the story — characterize the email by what it \
actually says and lead with the concrete cause and fix ("API disabled because \
the org is out of usage credits — top up / enable auto-reload"), never a vague \
"action-needed on your account, go check". If you can't read the body, say \
only what the snippet supports.

You have TWO independent checks — do BOTH every time:

CHECK 1 — UPCOMING PLANS. Is the user about to do/go/attend something in the \
next ~2 hours (from the calendar or something they mentioned in chat)? If so, \
check whether the world still cooperates: travel_time from their home base \
(live traffic; walking if close) + get_weather for that time. Flag it if they'd \
want to leave earlier, bring an umbrella, or change plans.

CHECK 2 — THEIR INBOX (INDEPENDENT of CHECK 1 — a delivery or a reply is worth a \
heads-up on its own, even with nothing upcoming). Scan the recent unread email \
below for a NEW real-world thing they'd want to know NOW: \
(a) a package that just ARRIVED, is OUT FOR DELIVERY, or was LEFT AT THE DOOR \
("your projector was delivered", "Amazon: left at front door", a UPS/USPS/FedEx/\
DoorDash drop) — judge the CONTENT (a delivery happened) over the SENDER: this \
counts EVEN when it's from Amazon or another retailer/app that ALSO sends \
marketing, so do NOT wave a real delivery off as an "automated app email"; \
(b) a reply from an actual person; \
(c) an order / reservation / on-sale confirmation. \
If you see one the user likely hasn't seen, you MUST flag it — surfacing a \
delivery or a real reply is the single most useful thing a heartbeat does, and \
it is NOT a "stay silent" case; do not default to "..." when there's a real \
inbox item below. IGNORE machine/service/newsletter noise — deploys, CI, \
monitoring, marketing, review requests, receipts, and "shipped — arriving in N \
days" notices (a FUTURE arrival is not a NOW event) — those are never events the \
user needs from you.

Third-party news about a topic the user cares about is still newsletter/news \
noise, not personal account status. In particular, do NOT turn The Information, \
AlphaSignal, Substack, analyst notes, or other AI/Anthropic/Claude newsletters \
into "your API suspension/outage/resolution" unless the email is directly from \
Anthropic/Claude/Billing/Status or another account provider and says action is \
needed on THIS user's account. If recent history says the user topped up or \
resolved a usage-credit/billing issue, don't keep treating that issue as open \
unless a direct provider email contradicts it. "Out of usage credits" is a \
billing balance/credits issue, not a policy suspension.

Text the user if EITHER check found something genuinely worth knowing they \
likely don't already know (leave 15 min early — traffic; rain right when they \
planned to be out; the package they were waiting for just arrived; a real person \
replied). ONE short message, lead with the thing.

Never alert about baby feed/nap/bedtime timing — the baby system handles that. \
Before claiming an absence ("no reply yet"), verify it against the actual \
emails/events — never assert something you didn't check. Don't repeat an alert \
you already sent (check your own recent messages). Inbox lines tagged \
"[ALREADY TOLD THE USER …]" were surfaced in a previous alert: never mention \
them again, and never send a message that only re-references old items.

SECURITY EMAILS: when surfacing a security/account/password/verification \
alert, NEVER relay links from inside the email — texted "verify your account" \
links are indistinguishable from phishing and train bad habits. Name the \
service and what it claims, and tell the user to open that app/site directly \
themselves to check.

Otherwise reply with EXACTLY "..." — nothing upcoming in the next ~2h, \
conditions fine, nothing new in the inbox worth flagging, or you already told \
them. Most heartbeats MUST be silent. Never use a heartbeat to ask a question, \
request Google access, make small talk, report tool problems, or reply to / \
acknowledge an EARLIER message in the conversation — the user did NOT text you \
just now, so "got it" / "noted" responses to old messages are spam; a heartbeat \
is never a conversational turn."""


# A package that actually ARRIVED (not merely "shipped, arriving later", and not
# the "USPS Informed Delivery" mail-scan digest, which is why bare "delivery" is
# excluded). Surfacing a delivery is the heartbeat's highest-value job, but the
# cheap background model flip-flops on impersonal transactional mail at
# temperature — so when the pre-fetched inbox clearly shows one, we make the
# flag deterministic (the model still phrases it and dedups against what it
# already said) instead of leaving a coin-flip to sampling.
_DELIVERY_RE = re.compile(
    r"\b(delivered|out for delivery|left at (the )?(front )?door|"
    r"arriving today|dropped off (at|on))\b",
    re.I,
)


def _without_snippet(line: str) -> str:
    """Strip the trailing snippet parenthetical google.py appends to mail
    lines ("- [id: ...] from ... — <subject>  (<snippet>)"), leaving only the
    "[id: ...] from <sender> — <subject>" portion. Real carrier mail puts the
    delivery event in the SUBJECT ("Delivered: your package"); newsletter
    marketing copy that happens to say "delivered straight to your inbox"
    lives in the SNIPPET. Matching the whole line conflates the two, so any
    regex meant to detect a real delivery must only ever see the subject."""
    idx = line.find("  (")
    return line[:idx] if idx != -1 else line


def delivery_directive(gathered: str) -> str:
    """A hard MUST-surface directive when `gathered` (the pre-fetched inbox)
    shows a package actually arrived; '' otherwise. Appended AFTER the gathered
    block so it's the last thing the model reads — countering the strong
    'most heartbeats must be silent' default for this one high-value case.
    Lines already marked as surfaced (identity dedup) don't count.

    Only the subject/sender portion of each mail line is scanned — the
    trailing snippet is stripped first (see `_without_snippet`) — so a
    newsletter's marketing snippet ("delivered straight to your inbox") can
    never trip this, only an actual delivery notice in the subject can."""
    fresh = "\n".join(
        _without_snippet(ln)
        for ln in (gathered or "").splitlines()
        if SEEN_MARK not in ln
    )
    if not _DELIVERY_RE.search(fresh):
        return ""
    return (
        "‼️ A DELIVERY just landed in the inbox above — a package arrived / was "
        "left at the door. Surfacing this is the entire point of CHECK 2: you "
        'MUST lead your reply with a one-line heads-up about it, and must NOT '
        'reply "...", UNLESS your own recent messages already told them about '
        "this same delivery."
    )


# ---------------------------------------------------------------------------
# Identity-keyed dedup for surfaced inbox items.
#
# The text-similarity suppressors in routes/message.py are heuristics — a
# reworded re-narration slips through, and (worse) a genuinely NEW alert can
# be eaten by a fuzzy match. This is the durable fix: every email line in the
# gathered block carries its Gmail message id; once an alert has told the user
# about an item, its id goes into profile.extra_data["hb_seen"] and future
# gathers annotate that line as already-surfaced. Identity never rewords.
# ---------------------------------------------------------------------------

SEEN_MARK = "[ALREADY TOLD THE USER — do not re-alert about this item]"

_MAIL_ID_RE = re.compile(r"\[id: ([A-Za-z0-9_-]+)\]")

_SEEN_STOP = frozenset(
    "the a an to of for and or in on at is it you your from re fw fwd with was "
    "were has have had this that new update notification".split()
)


def _line_words(line: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+", line.lower())
        if w not in _SEEN_STOP and len(w) > 2
    }


def annotate_seen(gathered: str, seen: dict[str, str]) -> str:
    """Tag every mail line whose Gmail id is already in `seen`."""
    if not seen:
        return gathered
    out = []
    for ln in gathered.splitlines():
        m = _MAIL_ID_RE.search(ln)
        if m and m.group(1) in seen:
            ln = f"{ln}  {SEEN_MARK}"
        out.append(ln)
    return "\n".join(out)


def ids_covered_by_alert(gathered: str, reply: str, directive_fired: bool) -> list[str]:
    """Gmail ids the alert `reply` plausibly told the user about: lines whose
    content words overlap the reply (>=2), plus every delivery-pattern line
    when the delivery directive forced the alert. Deliberately NOT 'everything
    in context' — an unmentioned item keeps its chance to alert later."""
    reply_words = _line_words(reply)
    covered: list[str] = []
    for ln in (gathered or "").splitlines():
        m = _MAIL_ID_RE.search(ln)
        if not m or SEEN_MARK in ln:
            continue
        if len(_line_words(ln) & reply_words) >= 2:
            covered.append(m.group(1))
        # Subject-only here too (see _without_snippet): a newsletter whose
        # SNIPPET happens to say "delivered" must not get marked "covered" as
        # a delivery just because the directive fired for some OTHER line.
        elif directive_fired and _DELIVERY_RE.search(_without_snippet(ln)):
            covered.append(m.group(1))
    return covered


def _prune_seen(seen: dict[str, str], now: datetime) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, ts in seen.items():
        try:
            when = datetime.fromisoformat(ts)
        except (TypeError, ValueError):
            continue
        if (now - when) < timedelta(hours=SEEN_TTL_HOURS):
            out[key] = ts
    return out


async def _load_seen(silo: str) -> dict[str, str]:
    from hal_orchestrator.services.profiles import get_profile

    async for session in db_session.get_session():
        profile = await get_profile(session, silo)
        seen = (profile.get("extra_data") or {}).get("hb_seen") or {}
        if not isinstance(seen, dict):
            return {}
        return _prune_seen(seen, datetime.now(timezone.utc))
    return {}


async def _mark_seen(silo: str, ids: list[str], prior: dict[str, str]) -> None:
    if not ids:
        return
    from hal_orchestrator.services.profiles import update_profile

    now = datetime.now(timezone.utc)
    merged = _prune_seen(dict(prior), now)
    for i in ids:
        merged[i] = now.isoformat()
    async for session in db_session.get_session():
        await update_profile(session, silo, hb_seen=merged)
        await session.commit()
        break
    log.info("heartbeat.marked_seen", silo=silo, n=len(ids))


def directive_bypass(directive: str, reply: str) -> bool:
    """Whether a fired delivery directive earns the right to bypass the
    proactive-send cooldown for THIS reply. A directive can fire on a false
    positive (e.g. a newsletter snippet — mitigated but not eliminated by
    subject-only scanning), so the bypass must also be confirmed by the
    model's own reply actually reading like a delivery alert. If the
    directive fired but the reply is generic (no delivery language), treat it
    as if there were no directive: the cooldown re-check applies as normal.
    This is safe even if a REAL delivery gets suppressed here — its gmail id
    is never marked seen in that case, so the next heartbeat (~15 min later)
    re-alerts on it."""
    return bool(directive) and bool(_DELIVERY_RE.search(reply or ""))


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
        try:
            # Recent UNREAD email — so the cheap model SEES new deliveries /
            # replies / confirmations without having to decide to look (it won't
            # for an old order not in recent chat — that's how the projector
            # delivery slipped through). Unread+recent naturally dedups: once the
            # user reads it, it stops resurfacing.
            mail = str(await execute_tool(
                "google_gmail",
                {"action": "list_emails", "query": "is:unread newer_than:1d", "max_results": 8},
                ctx,
            ))
            lines.append("Recent unread email:\n" + mail)
        except Exception:
            log.exception("heartbeat.gather_mail_failed", silo=silo)
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

    # Another proactive turn (a scheduled brief/digest cron) is mid-flight for
    # this silo right now — defer to it rather than racing out a duplicate.
    # This is the cheap early exit; the pre-delivery re-check below is the
    # belt-and-suspenders for the reverse ordering.
    if state.is_proactive_inflight(silo):
        log.info("heartbeat.inflight_skip", silo=silo)
        return

    # Hand the model real anticipation material up front (the cheap model won't
    # go fetch it on its own).
    prompt = HEARTBEAT_PROMPT
    context = await _gather_context(settings, http, silo)
    directive = ""
    seen: dict[str, str] = {}
    if context:
        # Identity dedup: annotate items already surfaced in a prior alert so
        # the model (and the delivery directive) treat them as old news.
        try:
            seen = await _load_seen(silo)
        except Exception:
            log.exception("heartbeat.load_seen_failed", silo=silo)
        context = annotate_seen(context, seen)
        prompt += "\n\n## Gathered for you (reason over this — don't re-fetch):\n" + context
        directive = delivery_directive(context)
        if directive:
            prompt += "\n\n" + directive

    # Proactive-contact cooldown: if HAL already texted this silo unprompted
    # recently (any daemon), don't even run the check — the user hasn't
    # digested the last message, and stacked proactive sends are the #1
    # annoyance in the transcripts. A hard delivery directive bypasses (a
    # package at the door is worth a second text).
    if not directive:
        since = state.minutes_since_proactive_send(silo)
        if since is not None and since < settings.heartbeat_alert_cooldown_minutes:
            log.info("heartbeat.cooldown_skip", silo=silo, minutes=round(since))
            return

    payload: dict = {
        "message_id": internal_message_id("heartbeat", silo, prompt),
        "phone": silo,
        "text": prompt,
        "is_group": is_group,
        "internal": True,
        # Background model (whatever's funded — see gemini_background_model).
        # MEDIUM is the verified-good level for the Gemini/Opus path; ignored on
        # a Haiku background model (the Claude shim runs Haiku thinking-less).
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
        # Race-closer: another proactive turn may have DELIVERED while this
        # heartbeat was gathering + thinking (the cron marks "sent" only at
        # delivery, ~16s after this heartbeat first checked the cooldown). Re-
        # check right before sending so a brief that just went out suppresses
        # this duplicate. The directive only bypasses this re-check when the
        # model's OWN reply also reads like a delivery alert — a directive
        # that fired on a false positive (newsletter, misfire) must not force
        # out an unrelated reply on top of a brief that just went out; see
        # directive_bypass().
        if not directive_bypass(directive, reply):
            since = state.minutes_since_proactive_send(silo)
            if since is not None and since < settings.heartbeat_alert_cooldown_minutes:
                log.info("heartbeat.cooldown_skip_late", silo=silo, minutes=round(since))
                return
        await state.outbox.put({"to": silo, "text": reply})
        state.mark_proactive_send(silo)
        log.info("heartbeat.alerted", silo=silo, chars=len(reply))
        # Durably record which inbox items this alert covered, so the next
        # gather annotates them and the model never re-narrates them.
        try:
            await _mark_seen(
                silo, ids_covered_by_alert(context, reply, bool(directive)), seen
            )
        except Exception:
            log.exception("heartbeat.mark_seen_failed", silo=silo)
    for sm in data.get("side_messages", []):
        if sm.get("to") and sm.get("text"):
            await state.outbox.put({"to": sm["to"], "text": sm["text"]})


async def heartbeat_loop(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    if not settings.heartbeat_enabled:
        return

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
                now = datetime.now(timezone.utc)
                candidates = await _active_silos(settings)
                due = due_silos(candidates, last_run, now, settings)
                if not due:
                    continue
                # Quiet hours are evaluated in EACH SILO'S OWN timezone (from
                # its profile), not a single global one — an LA user shouldn't
                # get 4am heartbeats because it's 7am in New York. A silo
                # skipped for quiet hours keeps its due-ness (no last_run
                # write) so it fires when its local morning starts.
                tz_by_silo: dict[str, ZoneInfo] = {}
                async for session in db_session.get_session():
                    from hal_orchestrator.services.profiles import get_profile

                    for silo in due:
                        try:
                            tz_by_silo[silo] = resolve_tz(await get_profile(session, silo))
                        except Exception:
                            tz_by_silo[silo] = USER_TZ
                    break
                for silo in due:
                    if not in_active_hours(
                        datetime.now(tz_by_silo.get(silo, USER_TZ)), settings
                    ):
                        continue
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
