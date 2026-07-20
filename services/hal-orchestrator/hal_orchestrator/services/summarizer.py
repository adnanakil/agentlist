"""Background conversation summarizer.

A separate daemon from the skills curator (which only runs every ~7 days after a
2h idle gate — far too slow for conversation context). This loop wakes every
~20 min and, after a short quiet period, refreshes a rolling long-horizon summary
for any conversation that has accumulated enough new turns. The summary preserves
context beyond the recent-turn window without re-feeding the whole transcript.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import HalOrchestratorConfig
from ag_db import session as db_session
from ag_db.models import HalConversation
from hal_orchestrator.services.curator import idle_seconds
from hal_orchestrator.services.gemini import call_gemini
from hal_orchestrator.services.identity import is_group_id

log = structlog.get_logger()

SUMMARY_INTERVAL_SECONDS = 60 * 20  # how often the loop wakes
SUMMARY_MIN_IDLE_SECONDS = 120  # don't summarize mid-burst
SUMMARY_MIN_NEW_MESSAGES = 6  # only refresh after meaningful new activity

SUMMARIZER_PROMPT = """\
You maintain a rolling summary of an ongoing iMessage assistant conversation.
Given the PRIOR SUMMARY and the RECENT MESSAGES, produce an UPDATED concise
summary (<= 180 words, plain text, no preamble or headers) capturing:
- durable facts, decisions, and preferences the user revealed
- ongoing or multi-step tasks and what the user is currently trying to accomplish
Merge new info into the prior summary; drop stale one-off chatter. Output ONLY
the summary text."""

# Group summaries feed the group-context catalog (services/group_catalog.py),
# where a member's own DM only ever sees a ~150-char head of this text. A
# plain recap buries the one thing that head needs to carry: what was
# actually decided. This addendum is appended only for group silos.
GROUP_SUMMARY_ADDENDUM = """
This conversation is a GROUP chat. LEAD the summary with concrete decisions, \
plans, and future-dated commitments made in the group (who/what/when — with \
actual dates/times), before any general recap. Preserve each one until its \
date has passed; don't let newer chatter crowd them out."""


def _summarizer_system_prompt(silo: str) -> str:
    """The summarizer's system prompt, with the group-decisions addendum
    appended when `silo` is a group (mirrors the enricher's _pick_prompt)."""
    if is_group_id(silo):
        return SUMMARIZER_PROMPT + "\n" + GROUP_SUMMARY_ADDENDUM
    return SUMMARIZER_PROMPT


async def _summarize_one(
    session: AsyncSession,
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
    conv: HalConversation,
) -> None:
    history = conv.history if isinstance(conv.history, list) else []
    recent: list[str] = []
    for t in history[-30:]:
        role = t.get("role", "")
        txt = " ".join(p.get("text", "") for p in t.get("parts", []) if "text" in p)
        if txt.strip():
            recent.append(f"{role}: {txt}")
    if not recent:
        return

    payload = (
        f"PRIOR SUMMARY:\n{conv.summary or '(none yet)'}\n\n"
        f"RECENT MESSAGES:\n" + "\n".join(recent)
    )
    resp = await call_gemini(
        http,
        settings,
        [{"role": "user", "parts": [{"text": payload}]}],
        system=_summarizer_system_prompt(conv.phone),
        model=settings.gemini_flash_model,
    )
    if not resp:
        return
    try:
        parts = resp["candidates"][0]["content"].get("parts", [])
    except (KeyError, IndexError):
        return
    text = "\n".join(p.get("text", "") for p in parts if "text" in p).strip()
    if text:
        # Conditional write: only land the summary if the conversation is
        # still the one we summarized. A membership-epoch cut (or /clear)
        # that raced the slow LLM call above resets message_count — writing
        # unconditionally would resurrect a summary of pre-cut content into
        # a thread whose new member must never see it.
        from sqlalchemy import update as sa_update

        landed = (
            await session.execute(
                sa_update(HalConversation)
                .where(
                    HalConversation.phone == conv.phone,
                    HalConversation.message_count == conv.message_count,
                )
                .values(summary=text[:2000])
                .returning(HalConversation.id)
            )
        ).scalar_one_or_none()
        if landed is None:
            log.info("summarizer.skipped_stale", phone=conv.phone)
            return
        conv.summary = text[:2000]
        conv.summarized_at_count = conv.message_count
        await session.flush()
        log.info("summarizer.updated", phone=conv.phone, count=conv.message_count)


async def _summary_pass(
    session: AsyncSession,
    settings: HalOrchestratorConfig,
    http: httpx.AsyncClient,
) -> None:
    stmt = (
        select(HalConversation)
        .where(
            (HalConversation.message_count - HalConversation.summarized_at_count)
            >= SUMMARY_MIN_NEW_MESSAGES
        )
        .limit(10)
    )
    rows = (await session.execute(stmt)).scalars().all()
    for conv in rows:
        try:
            await _summarize_one(session, settings, http, conv)
        except Exception:
            log.exception("summarizer.one_failed", phone=conv.phone)
    await session.commit()


async def summarizer_loop(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    """Long-running background task. Cancelled on app shutdown."""
    if not settings.curator_enabled:
        return

    while db_session._session_factory is None:
        await asyncio.sleep(1)
    Session = db_session._session_factory

    log.info("summarizer.started", interval=SUMMARY_INTERVAL_SECONDS)
    try:
        while True:
            try:
                if idle_seconds() >= SUMMARY_MIN_IDLE_SECONDS:
                    async with Session() as session:
                        await _summary_pass(session, settings, http)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("summarizer.tick_error")
            await asyncio.sleep(SUMMARY_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        log.info("summarizer.stopped")
        raise
