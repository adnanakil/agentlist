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

import httpx
import structlog

from ag_common.config import HalOrchestratorConfig
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


CRITIC_SYSTEM = """You are HAL's plan checker — a SKEPTICAL second pair of eyes on a reply HAL is about to send by text. You get the user's request, the facts HAL gathered, and the proposed reply. Assume it has at least one real flaw; look hard before clearing it. Do NOT rubber-stamp and do NOT nitpick tone.

Check, in order:
1. GOAL & REQUIRED STATE. What is the user actually trying to achieve? For each part of the plan, what condition does that part need to succeed? An activity you attend needs the attendee engaged/awake; a person's OWN appointment (facial, haircut, workout, meal) needs any dependent — a child — settled/asleep so they're hands-free; an outdoor item needs acceptable weather AT THAT TIME. Does the plan SATISFY those states or CONTRADICT them? (Classic contradiction: child asleep during the thing they came to experience, or awake/needing care during the parent's own appointment.)
2. CONSTRAINTS THAT DON'T BIND. For every limit the plan leans on (weather, hours, closures, traffic), check the gathered facts: does it actually apply in the RELEVANT window? Flag a daily/aggregate figure used to block or reshape a plan that only spans part of the day — e.g. a daily "% chance of rain" driven by an overnight band when the outing is midday.
3. HIDDEN TENSION. The single hardest trade-off in the request — does the reply resolve it, or hide it behind a confident timeline? If hidden, surface it.
4. EARNED CONFIDENCE. Is the reply most emphatic exactly where it's weakest?

Output STRICT JSON only:
{"flawed": <bool>, "issues": [<short specific problem>, ...], "revised_reply": "<full corrected reply text, or empty string if no change needed>"}

Set flawed=true ONLY for substantive errors in 1-3 (not tone, not polish). When you revise: fix ONLY the flawed parts, keep HAL's voice, and preserve every real detail — times, place names, links, prices — that wasn't wrong. Keep it iMessage-style (no markdown)."""


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
    http: httpx.AsyncClient,
    settings: HalOrchestratorConfig,
    history: list,
    user_text: str,
    reply: str,
    silo: str,
) -> tuple[str, dict]:
    """Return (final_reply, report). report['caught'] is True iff the critic
    found a substantive flaw AND produced a different, usable revision."""
    payload = {
        "request": (user_text or "")[:1500],
        "facts_gathered": _gathered_facts(history),
        "proposed_reply": reply[:3000],
    }
    log.info("critic.run", silo=silo)  # visible even when it clears the plan
    resp = await call_gemini(
        http,
        settings,
        [{"role": "user", "parts": [{"text": json.dumps(payload, indent=1)}]}],
        system=CRITIC_SYSTEM,
        model=settings.gemini_model,  # pro — subtle reasoning errors need it
        # Inherit the generous default — at thinking HIGH, a low cap truncates
        # the revised reply the same way it truncated the original.
    )
    if not resp:
        return reply, {"caught": False}
    try:
        parts = resp["candidates"][0]["content"].get("parts", [])
    except (KeyError, IndexError):
        return reply, {"caught": False}
    obj = _parse_json("\n".join(p.get("text", "") for p in parts if "text" in p))

    issues = [str(i)[:200] for i in (obj.get("issues") or [])][:5]
    if not obj.get("flawed"):
        return reply, {"caught": False, "issues": issues}
    revised = (obj.get("revised_reply") or "").strip()
    if not revised or revised == reply.strip():
        # Flagged but no usable rewrite — keep the original, but the issues
        # still feed the growth loop via the caller's friction log.
        return reply, {"caught": False, "issues": issues}
    log.info("critic.revised", silo=silo, issues=issues)
    return revised, {"caught": True, "issues": issues}
