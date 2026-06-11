"""Conversation history management — load, save, validate (Postgres)."""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalConversation

log = structlog.get_logger()


async def load_conversation(session: AsyncSession, phone: str) -> list[dict]:
    """Load conversation history for a phone number. Uses SELECT ... FOR UPDATE
    to prevent concurrent modifications."""
    stmt = (
        select(HalConversation)
        .where(HalConversation.phone == phone)
        .with_for_update()
    )
    result = await session.execute(stmt)
    conv = result.scalar_one_or_none()

    if conv is None:
        return []

    history = conv.history if isinstance(conv.history, list) else []
    return validate_history(history)


async def save_conversation(
    session: AsyncSession,
    phone: str,
    history: list[dict],
    max_turns: int = 40,
) -> None:
    """Save conversation history, trimming to max_turns if needed."""
    # Trim old turns (keep most recent).
    # Find a safe trim point that doesn't split a functionCall/functionResponse pair.
    if len(history) > max_turns * 2:
        start = len(history) - (max_turns * 2)
        # Advance past any functionResponse or functionCall entries at the cut point
        while start < len(history):
            parts = history[start].get("parts", [])
            has_fc = any("functionCall" in p for p in parts)
            has_fr = any("functionResponse" in p for p in parts)
            if has_fc or has_fr:
                start += 1
            else:
                break
        history = history[start:]

    stmt = (
        select(HalConversation)
        .where(HalConversation.phone == phone)
        .with_for_update()
    )
    result = await session.execute(stmt)
    conv = result.scalar_one_or_none()

    if conv is None:
        conv = HalConversation(
            phone=phone,
            history=history,
            message_count=1,
        )
        session.add(conv)
    else:
        conv.history = history
        conv.message_count = conv.message_count + 1

    await session.flush()


async def get_summary(session: AsyncSession, phone: str) -> str:
    """Return the rolling long-horizon summary for a conversation, if any."""
    stmt = select(HalConversation.summary).where(HalConversation.phone == phone)
    return (await session.execute(stmt)).scalar_one_or_none() or ""


async def clear_conversation(session: AsyncSession, phone: str) -> None:
    """Clear conversation history for a phone number."""
    stmt = select(HalConversation).where(HalConversation.phone == phone)
    result = await session.execute(stmt)
    conv = result.scalar_one_or_none()
    if conv:
        conv.history = []
        conv.message_count = 0
        conv.summary = ""
        conv.summarized_at_count = 0
        await session.flush()


def validate_history(history: list[dict]) -> list[dict]:
    """Validate conversation history for Gemini format compliance.

    Gemini requires:
    - Every functionCall (model turn) is immediately followed by functionResponse (user turn)
    - No consecutive same-role messages (except functionCall → functionResponse pairs)
    - History starts with a user turn

    This function removes orphaned entries and fixes broken sequences caused by
    history trimming cutting in the middle of functionCall/functionResponse pairs.
    """
    if not history:
        return []

    # --- Pass 1: pair up functionCall/functionResponse entries, drop orphans ---
    paired: list[dict] = []

    i = 0
    while i < len(history):
        entry = history[i]
        parts = entry.get("parts", [])

        if not parts:
            i += 1
            continue

        has_func_call = any("functionCall" in p for p in parts)
        has_func_response = any("functionResponse" in p for p in parts)

        if has_func_response and not has_func_call:
            # Orphaned functionResponse (no preceding functionCall) — skip
            log.warning("conversation.orphaned_func_response")
            i += 1
            continue

        if has_func_call:
            # Must be followed by a functionResponse
            next_entry = history[i + 1] if i + 1 < len(history) else None
            if next_entry and any(
                "functionResponse" in p for p in next_entry.get("parts", [])
            ):
                # Valid pair — keep both
                paired.append(entry)
                paired.append(next_entry)
                i += 2
                continue
            else:
                # Dangling functionCall with no response — skip it
                log.warning("conversation.dangling_func_call_removed")
                i += 1
                continue

        # Regular text entry
        paired.append(entry)
        i += 1

    # --- Pass 2: merge consecutive same-role text entries ---
    cleaned: list[dict] = []

    for entry in paired:
        role = entry.get("role")
        parts = entry.get("parts", [])
        has_func_call = any("functionCall" in p for p in parts)
        has_func_response = any("functionResponse" in p for p in parts)

        if cleaned and cleaned[-1].get("role") == role and not has_func_call and not has_func_response:
            existing_text = ""
            for p in cleaned[-1].get("parts", []):
                if "text" in p:
                    existing_text = p["text"]
            new_text = ""
            for p in parts:
                if "text" in p:
                    new_text = p["text"]
            if existing_text and new_text:
                cleaned[-1]["parts"] = [{"text": existing_text + "\n" + new_text}]
                continue

        cleaned.append(entry)

    # --- Pass 3: ensure history starts with a user turn ---
    while cleaned and cleaned[0].get("role") != "user":
        cleaned.pop(0)

    return cleaned
