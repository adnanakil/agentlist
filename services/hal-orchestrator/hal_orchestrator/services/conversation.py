"""Conversation history management — load, save, validate (Postgres)."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalConversation

log = structlog.get_logger()


@dataclass(frozen=True)
class ConversationSnapshot:
    history: list[dict]
    version: int


async def load_conversation_snapshot(
    session: AsyncSession, phone: str
) -> ConversationSnapshot:
    """Read a conversation without holding a lock across model/network work."""
    result = await session.execute(
        select(HalConversation.history, HalConversation.version).where(
            HalConversation.phone == phone
        )
    )
    row = result.one_or_none()
    if row is None:
        return ConversationSnapshot([], 0)
    history = row.history if isinstance(row.history, list) else []
    return ConversationSnapshot(validate_history(history), int(row.version or 0))


async def load_conversation(session: AsyncSession, phone: str) -> list[dict]:
    """Compatibility wrapper returning only the validated history."""
    return (await load_conversation_snapshot(session, phone)).history


def _trim_history(history: list[dict], max_turns: int) -> list[dict]:
    """Trim without splitting a functionCall/functionResponse pair."""
    if len(history) <= max_turns * 2:
        return history
    start = len(history) - (max_turns * 2)
    while start < len(history):
        parts = history[start].get("parts", [])
        if any("functionCall" in p or "functionResponse" in p for p in parts):
            start += 1
        else:
            break
    return history[start:]


async def save_conversation(
    session: AsyncSession,
    phone: str,
    history: list[dict],
    max_turns: int = 40,
    *,
    expected_version: int | None = None,
    append_entries: list[dict] | None = None,
    _retry_count: int = 0,
) -> None:
    """Save history with optional optimistic append/merge semantics."""
    history = _trim_history(history, max_turns)

    if expected_version is not None:
        updated = (
            await session.execute(
                update(HalConversation)
                .where(
                    HalConversation.phone == phone,
                    HalConversation.version == expected_version,
                )
                .values(
                    history=history,
                    message_count=HalConversation.message_count + 1,
                    version=HalConversation.version + 1,
                )
                .returning(HalConversation.id)
            )
        ).scalar_one_or_none()
        if updated is not None:
            return

        if expected_version == 0:
            inserted = (
                await session.execute(
                    insert(HalConversation)
                    .values(
                        phone=phone,
                        history=history,
                        message_count=1,
                        version=1,
                    )
                    .on_conflict_do_nothing(index_elements=["phone"])
                    .returning(HalConversation.id)
                )
            ).scalar_one_or_none()
            if inserted is not None:
                return

        # Another turn won the version race. Preserve its result and append only
        # this turn's new entries, then retry against the fresh version.
        if _retry_count >= 3:
            raise RuntimeError(f"conversation update contention for {phone}")
        fresh = await load_conversation_snapshot(session, phone)
        additions = append_entries if append_entries is not None else history
        merged = validate_history([*fresh.history, *additions])
        await save_conversation(
            session,
            phone,
            merged,
            max_turns=max_turns,
            expected_version=fresh.version,
            append_entries=additions,
            _retry_count=_retry_count + 1,
        )
        return

    # Legacy callers still get a short row lock around the write itself.
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
            version=1,
        )
        session.add(conv)
    else:
        conv.history = history
        conv.message_count = conv.message_count + 1
        conv.version = conv.version + 1

    await session.flush()


async def get_summary(session: AsyncSession, phone: str) -> str:
    """Return the rolling long-horizon summary for a conversation, if any."""
    stmt = select(HalConversation.summary).where(HalConversation.phone == phone)
    return (await session.execute(stmt)).scalar_one_or_none() or ""


async def clear_conversation(session: AsyncSession, phone: str) -> None:
    """Clear conversation history for a phone number.

    Bumps the optimistic version so an IN-FLIGHT turn that loaded pre-clear
    history fails its versioned save and falls into the merge path — which
    appends only that turn's new entries onto the cleared history. Without
    the bump, a racing save could resurrect the entire pre-clear transcript
    (fatal for membership-epoch cuts)."""
    stmt = select(HalConversation).where(HalConversation.phone == phone)
    result = await session.execute(stmt)
    conv = result.scalar_one_or_none()
    if conv:
        conv.history = []
        conv.message_count = 0
        conv.summary = ""
        conv.summarized_at_count = 0
        conv.version = (conv.version or 0) + 1
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
