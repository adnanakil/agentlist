"""Self-critique pass — a gated, adversarial second look at plan/recommendation
replies before they're sent (the hardening "Layer 2").

The main tool-use loop reasons under its own prompt template, which can anchor
it into a confidently-wrong plan (baby asleep through the museum, awake during
the parent's facial; an indoor "pivot" for rain that only falls overnight). The
critic re-reads the request + the facts already gathered + the proposed reply
from a FRESH, skeptical frame — no baby-itinerary template priming — and revises
only substantive errors. ONE no-tools model call, gated to synthesis-heavy turns
so it doesn't tax every message, and it reasons over gathered facts (no
re-search).

It also feeds the cheap layer: every catch logs friction (KIND_CRITIC_CATCH) so
the nightly growth loop can distill recurring catches into a playbook entry —
then the free in-prompt layer prevents it next time and the critic is freed for
the next unknown.
"""

from __future__ import annotations

import json
import re

import structlog

from hal_orchestrator.services.gemini import call_gemini

log = structlog.get_logger()

# A timed itinerary mentions several clock times; a plan/recommendation request
# is the other trigger. Together these target the failure class (multi-constraint
# plans) without critiquing every chit-chat or quick fact.
_CLOCK_RE = re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b", re.I)
_PLAN_REQUEST_RE = re.compile(
    r"\b(plan|itinerary|schedule|what should|should i|recommend|suggest|"
    r"where should|organi[sz]e|figure out|map out)\b",
    re.I,
)
MIN_REPLY_CHARS = 200


def should_critique(
    user_text: str, reply: str, total_tool_calls: int, is_group: bool
) -> bool:
    """Gate: only plan/recommendation turns. Cost-bounded — most turns skip."""
    if not reply or len(reply) < MIN_REPLY_CHARS:
        return False
    if len(_CLOCK_RE.findall(reply)) >= 3:
        return True  # a timed schedule
    if (
        _PLAN_REQUEST_RE.search(user_text or "")
        and total_tool_calls >= 2
        and len(reply) > 400
    ):
        return True  # an explicit, researched plan/recommendation
    return False


CRITIC_TOOLS = [
    "current_time", "google_calendar",
    "travel_time", "web_search", "web_fetch", "resy",
]
CRITIC_MAX_ITERS = 6  # tool-call rounds before forcing a verdict

CRITIC_SYSTEM = """You are HAL's plan VERIFIER. Before HAL sends a plan/recommendation, you surface its load-bearing ASSUMPTIONS and actually VERIFY the checkable ones with tools. You have READ-ONLY access to the user's calendar, the web, maps/travel time, restaurant availability, and the clock. Most well-formed plans are fine — but a plan built on an UNVERIFIED assumption is the failure you exist to catch.

STEP 1 — ASSUMPTIONS. List what the plan silently assumes. The most dangerous and most common: WHEN is this happening? A plan that assumes an event/trip/reservation/flight/appointment is happening TODAY or right now — when it could be a future date — is the classic failure. Other assumptions: the place is open at that time; the travel time; availability; who's going; the weather.

STEP 2 — VERIFY with tools. For each checkable assumption, CHECK it — never trust the plan's implicit guess:
- Timing of a KNOWN event (a trip, an Airbnb, a reservation, a flight, an appointment): call current_time for today's date, THEN check the user's calendar (google_calendar) to find the booking's ACTUAL date. NEVER assume the event is today just because the user asked today.
- Places / hours / open-now: web_search. Restaurants: resy.
- Travel time: travel_time.
(google_calendar works only in 1:1 chats; if a tool says it's unavailable, note that and verify what you can.)

STEP 3 — VERDICT. A flaw is SUBSTANTIVE when a VERIFIED fact changes the plan: the real date is different, a place is closed then, the travel time is off, a required state is backwards (e.g. a child asleep during the thing they came to see), or a constraint doesn't actually bind. If a load-bearing assumption turns out FALSE (e.g. the trip is next week, not today), the plan IS flawed — revise it. If you now know the corrected key fact but can't fully rebuild the plan (e.g. you know the real date but not that day's schedule), correct the fact and say what's needed: e.g. "Heads up — your Accord trip is next Saturday, not today. Want me to time the departure for that morning instead?"

Do NOT flag cosmetic things: renumbering, wording, tone, emojis, formatting, or anything that leaves the times/dates/places/states unchanged. If your "fix" leaves the plan materially the same, set flawed=false.

When you've finished verifying, reply with STRICT JSON only (no tool call):
{"flawed": <bool>, "issues": [<short specific problem with what you VERIFIED>, ...], "change_summary": "<one short phrase, e.g. 'trip is next Sat, not today' — empty if not flawed>", "revised_reply": "<full corrected reply, or empty if not flawed>"}
When you revise: keep HAL's voice + every correct detail; iMessage-style, no markdown."""

# A revised reply this textually close to the original is cosmetic, not a real
# fix — never send it as a "correction" (backstop behind the prompt rules).
_COSMETIC_SIMILARITY = 0.90


def _gathered_facts(history: list) -> list[str]:
    """Pull the tool-result texts out of the conversation so the critic can
    check constraint-binding against the SAME data HAL saw — without the
    system-prompt template that anchored the original plan."""
    facts: list[str] = []
    for turn in history:
        for p in turn.get("parts", []):
            fr = p.get("functionResponse")
            if isinstance(fr, dict):
                content = (fr.get("response") or {}).get("content")
                if content:
                    facts.append(str(content)[:500])
    return facts[-12:]


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        start = text.find("{")
        if start == -1:
            return {}
        text = text[start:]
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


async def critique_and_revise(
    ctx,
    history: list,
    user_text: str,
    reply: str,
) -> tuple[str, dict]:
    """Verify the plan's assumptions with READ-ONLY tools, then return
    (final_reply, report). report['caught'] is True iff a substantive flaw was
    found AND a different, usable revision produced. `ctx` is the live
    ToolContext (silo, session, http, settings) so the critic can check the
    user's calendar/email/the web. Runs on the cheap background model."""
    from hal_orchestrator.prompts.tool_defs import get_agent_tools
    from hal_orchestrator.tools.registry import execute_tool

    silo = ctx.phone
    settings = ctx.settings
    http = ctx.http_client

    payload = {
        "request": (user_text or "")[:1500],
        "facts_gathered": _gathered_facts(history),
        "proposed_reply": reply[:3000],
    }
    log.info("critic.run", silo=silo)
    tools = get_agent_tools(CRITIC_TOOLS)
    critic_history: list = [
        {"role": "user", "parts": [{"text": json.dumps(payload, indent=1)}]}
    ]

    obj: dict = {}
    for _ in range(CRITIC_MAX_ITERS):
        resp = await call_gemini(
            http,
            settings,
            critic_history,
            tools=tools,
            system=CRITIC_SYSTEM,
            # Background model (cheap flash) — always-on infra; strong at tool
            # use, so it can actually go check email/calendar.
            model=settings.gemini_background_model,
            thinking_level="MEDIUM",
        )
        if not resp:
            return reply, {"caught": False}
        parts = (resp.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        func_calls = [p for p in parts if "functionCall" in p]
        if func_calls:
            critic_history.append({"role": "model", "parts": parts})
            responses = []
            for fc in func_calls:
                call = fc["functionCall"]
                out = await execute_tool(call["name"], call.get("args", {}), ctx)
                responses.append(
                    {"functionResponse": {"name": call["name"], "response": {"content": out}}}
                )
            critic_history.append({"role": "user", "parts": responses})
            log.info(
                "critic.verifying",
                silo=silo,
                tools=[fc["functionCall"]["name"] for fc in func_calls],
            )
            continue
        obj = _parse_json("\n".join(p.get("text", "") for p in parts if "text" in p))
        break

    issues = [str(i)[:200] for i in (obj.get("issues") or [])][:5]
    summary = (obj.get("change_summary") or "").strip()[:200]
    if not obj.get("flawed"):
        return reply, {"caught": False, "issues": issues}
    revised = (obj.get("revised_reply") or "").strip()
    if not revised or revised == reply.strip():
        # Flagged but no usable rewrite — keep the original, but the issues
        # still feed the growth loop via the caller's friction log.
        return reply, {"caught": False, "issues": issues}
    # Cosmetic backstop: if the "fix" is nearly identical to the original (e.g.
    # renumbered naps, reworded line), it's not worth a follow-up — sending it
    # reads as "nothing changed". Suppress it.
    import difflib

    similarity = difflib.SequenceMatcher(None, reply.strip(), revised).ratio()
    if similarity >= _COSMETIC_SIMILARITY:
        log.info("critic.cosmetic_suppressed", silo=silo, similarity=round(similarity, 3))
        return reply, {"caught": False, "issues": issues, "cosmetic": True}
    log.info("critic.revised", silo=silo, issues=issues, similarity=round(similarity, 3))
    return revised, {"caught": True, "issues": issues, "summary": summary}
