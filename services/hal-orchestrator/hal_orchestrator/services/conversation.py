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
    # Trim old turns (keep most recent)
    if len(history) > max_turns * 2:
        history = history[-(max_turns * 2) :]

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


async def clear_conversation(session: AsyncSession, phone: str) -> None:
    """Clear conversation history for a phone number."""
    stmt = select(HalConversation).where(HalConversation.phone == phone)
    result = await session.execute(stmt)
    conv = result.scalar_one_or_none()
    if conv:
        conv.history = []
        conv.message_count = 0
        await session.flush()


def validate_history(history: list[dict]) -> list[dict]:
    """Validate conversation history for Gemini format compliance.

    Ensures:
    - functionResponse always follows functionCall
    - No consecutive same-role messages
    - Removes orphaned entries
    """
    if not history:
        return []

    cleaned: list[dict] = []

    for entry in history:
        role = entry.get("role")
        parts = entry.get("parts", [])

        if not parts:
            continue

        # Check if this entry has function calls or responses
        has_func_call = any("functionCall" in p for p in parts)
        has_func_response = any("functionResponse" in p for p in parts)

        if has_func_response:
            # Function responses must follow a function call
            if not cleaned or not any(
                "functionCall" in p for p in cleaned[-1].get("parts", [])
            ):
                log.warning("conversation.orphaned_func_response", phone="unknown")
                continue

        # Avoid consecutive same-role messages (merge or skip)
        if cleaned and cleaned[-1].get("role") == role and not has_func_call and not has_func_response:
            # Merge text parts
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

    return cleaned
