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


CRITIC_SYSTEM = """You are HAL's plan checker — a skeptical second pair of eyes on a reply HAL already SENT by text. If (and only if) you find a SUBSTANTIVE flaw, HAL will send a follow-up correction. Most well-formed plans have NO substantive flaw — clearing one is the common, correct outcome. A needless "correction" that re-sends a near-identical plan is a BAD outcome you must avoid.

A flaw is SUBSTANTIVE only if fixing it changes at least one of:
- an actual CLOCK TIME in the schedule, or
- a required STATE assignment (someone/something needs to be awake vs asleep, dry vs not, open vs closed — and the plan has it backwards), or
- a CONSTRAINT that doesn't actually bind (e.g. a daily "% chance of rain" used to reshape a midday plan when the gathered hourly data shows rain only overnight), or
- a place/fact that the gathered facts show is WRONG (closed at that time, wrong location, etc.).

Check for those, in order: (1) required-state contradictions — child asleep during the thing they came to experience, or awake/needing care during the parent's own appointment; (2) constraints that don't bind in the relevant window; (3) a hidden critical tension; (4) a flat factual error vs the gathered facts.

Do NOT flag, and do NOT rewrite, for ANY of these — they are NOT substantive:
- renumbering or relabeling items (e.g. "Nap 1" vs "Nap 2", "first" vs "next"),
- wording, phrasing, tone, emojis, ordering of equivalent lines, or formatting,
- anything that leaves all the clock times, the awake/asleep assignments, and the named places UNCHANGED.
If your "fix" would produce essentially the same schedule with the same states, the plan is NOT flawed — set flawed=false.

Output STRICT JSON only:
{"flawed": <bool>, "issues": [<short specific problem>, ...], "change_summary": "<one short phrase naming what materially changed, e.g. 'moved nap to cover the facial' — empty if not flawed>", "revised_reply": "<full corrected reply, or empty string if not flawed>"}

When you revise: change ONLY the flawed parts, keep HAL's voice, and preserve every correct detail — times, place names, links, prices. iMessage-style, no markdown."""

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
        # Background model (cheap flash), NOT the main loop — the critic is
        # always-on infra; it shouldn't ride a premium main model's cost.
        model=settings.gemini_background_model,
        # MEDIUM keeps the verdict + full revised reply within budget.
        thinking_level="MEDIUM",
    )
    if not resp:
        return reply, {"caught": False}
    try:
        parts = resp["candidates"][0]["content"].get("parts", [])
    except (KeyError, IndexError):
        return reply, {"caught": False}
    obj = _parse_json("\n".join(p.get("text", "") for p in parts if "text" in p))

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
