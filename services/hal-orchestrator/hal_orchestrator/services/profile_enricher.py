"""Background profile enricher — the agent getting to know you over time.

A daemon (sibling of the summarizer) that, between conversations, distills
DURABLE knowledge from a silo's recent messages and merges it into the silo's
structured profile (`hal_user_profiles.notes`, injected into every turn):

- 1:1 silo  → a personal profile: preferences, routines, needs, constraints,
  important people/places, goals. The more the user talks, the richer it gets.
- group silo → a group profile: purpose/goals, members & dynamics, shared
  interests, norms. Group-level only — never a member's private personal data.

Distinct from the summarizer (a short rolling conversation recap that forgets
detail) and from memory (timestamped one-off events). This ACCUMULATES stable
knowledge. It preserves what's already in the profile and only adds/refines.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import HalOrchestratorConfig
from ag_db import session as db_session
from ag_db.models import HalConversation, HalUserMemory, HalUserProfile
from hal_orchestrator.services.curator import idle_seconds
from hal_orchestrator.services.gemini import call_gemini
from hal_orchestrator.services.identity import is_group_id
from hal_orchestrator.services.profiles import update_profile

log = structlog.get_logger()

ENRICH_INTERVAL_SECONDS = 60 * 30  # how often the loop wakes
ENRICH_MIN_IDLE_SECONDS = 120  # don't enrich mid-burst
ENRICH_MIN_NEW_MESSAGES = 8  # only re-enrich after meaningful new activity
ENRICH_BATCH = 8  # silos per pass
MAX_PROFILE_CHARS = 4000
MEMORY_LIMIT = 60  # most-recent memories to mine for long-horizon patterns
MEMORY_MAX_CHARS = 3500

_PERSON_PROMPT = """\
You maintain a durable PROFILE of ONE person that their personal AI assistant
reads on EVERY message to serve them better over time. You are given the CURRENT
PROFILE and RECENT MESSAGES from their conversation. Output an UPDATED profile.

Capture durable, reusable knowledge about this person:
- Preferences & style: how they like things done, communication style, tastes,
  brands/services they use, food/diet, clear likes & dislikes.
- Routines & schedule: recurring patterns, work hours, regular commitments.
- Constraints & needs: dietary, accessibility, budget, hard limits.
- People & places: important relationships, home base, frequent locations.
- Goals & ongoing projects: what they're working toward.

Rules:
- PRESERVE everything in the current profile that is still true. ADD durable
  facts revealed in the recent messages. Refine/correct facts that changed;
  remove only what is clearly outdated or contradicted.
- Durable facts only — NOT one-off events or timestamped happenings (those live
  in memory), and NEVER secrets, passwords, or codes.
- You MAY record a clear, repeated pattern as a preference (e.g. "usually asks
  for TL;DRs", "books aisle seats"), but do NOT fabricate or over-infer from thin
  evidence. High confidence only.
- You are ALSO given MEMORIES: a log of timestamped events/facts saved over a
  long period. Mine them for LONGER-TERM patterns the recent messages alone
  can't show — recurring quantities/timings (e.g. "naps usually run ~1h10"),
  repeated orders/choices, established habits and routines. Distill these into
  durable preferences/patterns; do NOT copy individual timestamped events.
- Organize as concise markdown with short section headers. Facts, not prose.
  Keep under ~400 words; tighten and dedupe as it grows.

Output ONLY the updated profile markdown, nothing else."""

_GROUP_PROMPT = """\
You maintain a durable PROFILE of a GROUP CHAT that an AI assistant reads to be
helpful in it. You are given the CURRENT PROFILE and RECENT MESSAGES from the
group. Output an UPDATED profile.

Capture what helps the assistant understand and serve THIS GROUP:
- Purpose & goals: what the group is for; what they're trying to do together.
- Members & dynamics: who's in it, their roles/relationships, how they interact.
- Shared interests & recurring topics: what they care about and discuss.
- Norms & style: tone, in-jokes, communication patterns, when to chime in.
- Assistant conduct in THIS group: how the members want the assistant to
  behave here. Feedback like "please chill", "keep it to yourself", "dial it
  back", or "stfu" is a durable norm — record it prominently (e.g. "Members
  want the assistant low-key: answer only when addressed, no chiming into
  their back-and-forth"), and keep it until members clearly invite more.
- Ongoing plans: trips, projects, decisions in progress.

Rules:
- PRESERVE what's still true; ADD insights from recent messages; refine as the
  group evolves.
- GROUP-level knowledge only. Do NOT record any member's private personal data
  (that belongs to their own 1:1, never here) — only group-relevant dynamics.
- No secrets/passwords. High-confidence observations only; don't over-infer.
- You are ALSO given MEMORIES: timestamped group events/facts saved over time.
  Use them to spot the group's longer-term patterns and recurring themes (what
  they repeatedly do, plan, or care about). Distill patterns; don't copy raw
  events.
- Organize as concise markdown with short headers. Under ~400 words; dedupe.

Output the updated profile markdown. THEN, on its own line, output exactly
===OBSERVATIONS=== followed by a JSON array of observations for individual
members' PERSONAL assistants — current, useful things happening to a specific
member, sourced from this group conversation: their stated plans, things
they're expecting or dealing with, commitments they made here ("planning a
Mattituck trip this weekend", "agreed to bring the cake Saturday").
Rules for observations:
- handle must be a sender handle seen in THIS transcript (the [+1...] prefix);
  observations for anyone else are dropped.
- Things about that member's own life only — never another member's private
  info, never baby feed/nap logging (already shared), never chit-chat.
- Style feedback a member gave the ASSISTANT also counts ("asked the
  assistant to be less enthusiastic / more brief with them") — it should
  follow that member into their 1:1 so the assistant matches their energy
  everywhere.
- 0-3 per member, one sentence each, self-contained (name the thing, the
  when, the where). Most runs: an empty array.
Format: [{"handle": "+1XXXXXXXXXX", "observation": "..."}] or []"""


def _build_transcript(history: list[dict], limit: int = 40) -> str:
    lines: list[str] = []
    for t in history[-limit:]:
        role = t.get("role", "")
        txt = " ".join(p.get("text", "") for p in t.get("parts", []) if "text" in p)
        if txt.strip():
            lines.append(f"{role}: {txt}")
    return "\n".join(lines)


async def _load_memories(session: AsyncSession, phone: str) -> str:
    """Most-recent memories for the silo, chronological, within a char budget.
    These are timestamped events/facts the assistant logged over time — fed to
    the enricher so it can spot long-horizon patterns the recent transcript
    can't (e.g. recurring nap lengths, repeated orders)."""
    rows = (
        await session.execute(
            select(HalUserMemory.content)
            .where(HalUserMemory.phone == phone)
            .order_by(HalUserMemory.created_at.desc())
            .limit(MEMORY_LIMIT)
        )
    ).scalars().all()
    kept: list[str] = []
    total = 0
    for content in rows:  # newest-first; keep most recent within budget
        if total + len(content) > MEMORY_MAX_CHARS:
            break
        kept.append(content)
        total += len(content)
    kept.reverse()  # display oldest-first so trends read naturally
    return "\n".join(f"- {c}" for c in kept)


def _pick_prompt(silo: str) -> str:
    return _GROUP_PROMPT if is_group_id(silo) else _PERSON_PROMPT


OBS_MARKER = "===OBSERVATIONS==="


def split_profile_and_observations(text: str) -> tuple[str, list[dict]]:
    """Split group-enricher output into (profile_md, observations). Missing or
    malformed observations degrade to none — the profile is never lost."""
    import json as _json

    if OBS_MARKER not in text:
        return text.strip(), []
    profile, _, rest = text.partition(OBS_MARKER)
    rest = rest.strip()
    if rest.startswith("```"):
        rest = rest.strip("`").removeprefix("json").strip()
    start = rest.find("[")
    if start == -1:
        return profile.strip(), []
    try:
        obj = _json.JSONDecoder().raw_decode(rest[start:])[0]
    except (ValueError, TypeError):
        return profile.strip(), []
    return profile.strip(), obj if isinstance(obj, list) else []


def _passes_guard(existing: str, new: str) -> bool:
    """Reject empty or catastrophically-shrunken output so a bad model response
    can never wipe an accumulated profile."""
    new = new.strip()
    if not new:
        return False
    if existing and len(new) < 0.4 * len(existing.strip()):
        return False
    return True


async def _enrich_one(
    session: AsyncSession,
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
    conv: HalConversation,
    existing_notes: str,
) -> bool:
    history = conv.history if isinstance(conv.history, list) else []
    transcript = _build_transcript(history)
    memories = await _load_memories(session, conv.phone)
    if not transcript and not memories:
        return False

    payload = (
        f"CURRENT PROFILE:\n{existing_notes or '(empty — build it from scratch)'}\n\n"
        f"MEMORIES (timestamped event/fact log — mine for long-horizon PATTERNS "
        f"and durable facts; do NOT copy individual events into the profile):\n"
        f"{memories or '(none yet)'}\n\n"
        f"RECENT MESSAGES:\n{transcript or '(none)'}"
    )
    resp = await call_gemini(
        http,
        settings,
        [{"role": "user", "parts": [{"text": payload}]}],
        system=_pick_prompt(conv.phone),
        model=settings.gemini_flash_model,
    )
    if not resp:
        return False
    try:
        parts = resp["candidates"][0]["content"].get("parts", [])
    except (KeyError, IndexError):
        return False
    raw = "\n".join(p.get("text", "") for p in parts if "text" in p).strip()

    # Group output may carry per-member observations after the profile — the
    # one-way valve into members' personal silos (group_observations.py).
    observations: list[dict] = []
    if is_group_id(conv.phone):
        new_notes, observations = split_profile_and_observations(raw)
    else:
        new_notes = raw

    if not _passes_guard(existing_notes, new_notes):
        log.warning("enricher.guard_skipped", silo=conv.phone)
        return False

    if observations:
        from hal_orchestrator.services.group_observations import (
            add_observations,
            extract_participants,
        )
        from hal_orchestrator.services.profiles import get_profile

        try:
            group_name = (await get_profile(session, conv.phone)).get("name") or ""
            n = await add_observations(
                session,
                conv.phone,
                group_name,
                observations,
                extract_participants(transcript),
            )
            if n:
                log.info("enricher.observations", silo=conv.phone, written=n)
        except Exception:
            log.exception("enricher.observations_failed", silo=conv.phone)

    await update_profile(
        session,
        conv.phone,
        notes=new_notes[:MAX_PROFILE_CHARS],
        enriched_at_count=conv.message_count,
    )
    log.info(
        "enricher.enriched",
        silo=conv.phone,
        is_group=is_group_id(conv.phone),
        chars=len(new_notes),
    )
    return True


async def _enrich_pass(
    session: AsyncSession,
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
) -> None:
    # Conversations that have accumulated enough new messages since last
    # enrichment (most-recently-active first). Outer join so silos without a
    # profile row yet (enriched_at_count = 0) are included.
    stmt = (
        select(HalConversation, HalUserProfile.notes)
        .outerjoin(HalUserProfile, HalUserProfile.phone == HalConversation.phone)
        .where(
            (
                HalConversation.message_count
                - func.coalesce(HalUserProfile.enriched_at_count, 0)
            )
            >= ENRICH_MIN_NEW_MESSAGES
        )
        .order_by(HalConversation.updated_at.desc())
        .limit(ENRICH_BATCH)
    )
    rows = (await session.execute(stmt)).all()
    for conv, notes in rows:
        try:
            await _enrich_one(session, settings, http, conv, notes or "")
        except Exception:
            log.exception("enricher.one_failed", silo=conv.phone)
    await session.commit()


async def profile_enricher_loop(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    """Long-running background task. Cancelled on app shutdown."""
    if not settings.curator_enabled:
        return

    while db_session._session_factory is None:
        await asyncio.sleep(1)
    Session = db_session._session_factory

    log.info("enricher.started", interval=ENRICH_INTERVAL_SECONDS)
    try:
        while True:
            try:
                if idle_seconds() >= ENRICH_MIN_IDLE_SECONDS:
                    async with Session() as session:
                        await _enrich_pass(session, settings, http)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("enricher.tick_error")
            await asyncio.sleep(ENRICH_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        log.info("enricher.stopped")
        raise
