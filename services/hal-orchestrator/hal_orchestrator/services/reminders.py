"""Reminder CRUD + background checker (Postgres)."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import HalOrchestratorConfig
from ag_db.models import HalReminder
from ag_db.session import get_session

log = structlog.get_logger()


# --------------------------------------------------------------------------- #
# Supersede detection — a reminder that replaces one just created for the same
# thing should kill the old one. Seen live 2026-06-23: "ping at 9:30" was
# re-negotiated to 10:00, both were created, and the 9:30 fired at exactly the
# moment the user had said not to ping him.
# --------------------------------------------------------------------------- #

_DUP_STOP = frozenset(
    "the a an to of for and or in on at is it you your me my with about что "
    "remind reminder check ask tell ping text this that next week today "
    "tomorrow am pm".split()
)


def _content_words(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if w not in _DUP_STOP and len(w) > 1
    }


def is_probable_duplicate(
    a: str, b: str, thr: float = 0.5, min_shared: int = 3
) -> bool:
    """Jaccard over content words — 'check with Seth about lunch day' vs
    'ask Seth what day works for lunch' land well above thr; unrelated
    reminders land below. min_shared guards the short-text trap: two 4-word
    reminders that share 2 topical words hit thr=0.5 while being genuinely
    different tasks ('call dentist re crown' / 'pick up crown at dentist') —
    auto-deleting one of those would eat a real reminder. Pure."""
    aw, bw = _content_words(a), _content_words(b)
    if not aw or not bw or len(aw & bw) < min_shared:
        return False
    return len(aw & bw) / len(aw | bw) >= thr


async def find_nearby_pending(
    session: AsyncSession,
    phone: str,
    due_at: datetime,
    exclude_id=None,
    window_hours: float = 6.0,
) -> list[HalReminder]:
    """Other unsent one-shot reminders in this silo due within ±window of
    `due_at` — candidates the new reminder may be superseding."""
    lo = due_at - timedelta(hours=window_hours)
    hi = due_at + timedelta(hours=window_hours)
    stmt = select(HalReminder).where(
        HalReminder.phone == phone,
        HalReminder.sent == False,  # noqa: E712
        HalReminder.recurrence.is_(None),
        HalReminder.due_at >= lo,
        HalReminder.due_at <= hi,
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return [r for r in rows if exclude_id is None or r.id != exclude_id]


async def create_reminder(
    session: AsyncSession,
    phone: str,
    text: str,
    due_at: datetime,
    recurrence: str | None = None,
    sender_phone: str | None = None,
    is_group: bool = False,
    group_name: str | None = None,
    cancel_if: str | None = None,
) -> dict:
    """Create a new reminder."""
    reminder = HalReminder(
        phone=phone,
        text=text,
        due_at=due_at,
        recurrence=recurrence,
        sender_phone=sender_phone,
        is_group=is_group,
        group_name=group_name,
        cancel_if=cancel_if,
    )
    session.add(reminder)
    await session.flush()

    import hal_orchestrator.state as _state

    log.info(
        "reminder.created",
        phone=phone,
        text=text[:50] if _state.settings.log_message_content else None,
        text_len=len(text or ""),
        due_at=str(due_at),
    )
    return {
        "id": str(reminder.id),
        "text": text,
        "due_at": str(due_at),
        "recurrence": recurrence,
    }


async def list_reminders(session: AsyncSession, phone: str) -> list[dict]:
    """List pending (unsent) reminders for a user."""
    stmt = (
        select(HalReminder)
        .where(HalReminder.phone == phone, HalReminder.sent == False)  # noqa: E712
        .order_by(HalReminder.due_at.asc())
    )
    result = await session.execute(stmt)
    reminders = result.scalars().all()

    return [
        {
            "id": str(r.id),
            "text": r.text,
            "due_at": str(r.due_at),
            "recurrence": r.recurrence,
        }
        for r in reminders
    ]


async def delete_reminder(session: AsyncSession, reminder_id: str, phone: str) -> bool:
    """Delete a reminder by ID (scoped to user's phone)."""
    from uuid import UUID

    try:
        uid = UUID(reminder_id)
    except ValueError:
        return False

    stmt = select(HalReminder).where(HalReminder.id == uid, HalReminder.phone == phone)
    result = await session.execute(stmt)
    reminder = result.scalar_one_or_none()

    if reminder is None:
        return False

    await session.delete(reminder)
    await session.flush()
    return True


# --------------------------------------------------------------------------- #
# Background checker
# --------------------------------------------------------------------------- #


async def run_reminder_checker(
    settings: HalOrchestratorConfig,
    http_client: httpx.AsyncClient,
) -> None:
    """Background task: check for due reminders and send them via the bridge."""
    log.info("reminder_checker.started")

    while True:
        try:
            await asyncio.sleep(settings.reminder_check_interval_seconds)
            await _check_and_send_reminders(settings, http_client)
        except asyncio.CancelledError:
            log.info("reminder_checker.cancelled")
            raise
        except Exception:
            log.exception("reminder_checker.error")
            await asyncio.sleep(10)


async def _check_and_send_reminders(
    settings: HalOrchestratorConfig,
    http_client: httpx.AsyncClient,
) -> None:
    """Check for due reminders and dispatch them."""
    now = datetime.now(timezone.utc)

    async for session in get_session():
        stmt = (
            select(HalReminder)
            .where(
                HalReminder.sent == False,  # noqa: E712
                HalReminder.due_at <= now,
            )
            .limit(50)
        )
        result = await session.execute(stmt)
        due_reminders = result.scalars().all()

        for reminder in due_reminders:
            try:
                # Snapshot before the gate may reword it — a recurring copy
                # should carry the original wording, not this occurrence's.
                original_text = reminder.text

                drop = False
                if reminder.cancel_if:
                    verdict = await _gate_reminder(
                        settings, http_client, session, reminder, now
                    )
                    if verdict is not None:
                        drop = verdict.drop
                        if not drop and verdict.text:
                            reminder.text = verdict.text

                reminder.sent = True

                # Handle recurrence (independent of send/drop — a daily reminder
                # that's moot today should still come back tomorrow).
                if reminder.recurrence:
                    next_due = _next_occurrence(reminder.due_at, reminder.recurrence)
                    if next_due:
                        new_reminder = HalReminder(
                            phone=reminder.phone,
                            text=original_text,
                            due_at=next_due,
                            recurrence=reminder.recurrence,
                            sender_phone=reminder.sender_phone,
                            is_group=reminder.is_group,
                            group_name=reminder.group_name,
                            cancel_if=reminder.cancel_if,
                        )
                        session.add(new_reminder)

                # COMMIT BEFORE DELIVERY, one reminder per transaction. The old
                # order (queue to outbox, mark sent, commit the whole batch at
                # the end) meant any DB error late in the batch rolled back
                # sent=True for reminders whose texts were ALREADY delivered —
                # the entire batch re-fired next tick as duplicates. A crash in
                # the new order loses at most one send, which beats double-
                # texting a batch. (expire_on_commit=False keeps the row's
                # attributes readable for the delivery below.)
                await session.commit()
            except Exception:
                log.exception(
                    "reminder.mark_failed",
                    reminder_id=str(reminder.id),
                    phone=reminder.phone,
                )
                # A failed statement aborts the transaction; without rollback
                # every later reminder in this batch would die on
                # PendingRollbackError.
                await session.rollback()
                continue

            if drop:
                log.info(
                    "reminder.gated_out",
                    reminder_id=str(reminder.id),
                    phone=reminder.phone,
                    text=original_text[:60] if settings.log_message_content else None,
                )
            else:
                await _send_reminder_via_bridge(
                    settings, http_client, session, reminder
                )


# --------------------------------------------------------------------------- #
# Fire-time relevance gate — let the model decide keep / drop / reword
# --------------------------------------------------------------------------- #


@dataclass
class GateVerdict:
    drop: bool
    text: str | None  # reworded reminder text, or None to keep as-is


GATE_SYSTEM = (
    "You are a relevance gate for a reminder that is about to be sent. The "
    "reminder was scheduled earlier against a PREDICTED event; you decide "
    "whether it's still worth sending now that real life has unfolded."
)


def build_gate_prompt(
    reminder_text: str, cancel_if: str, situation: str, now_str: str
) -> str:
    """The user-turn handed to the gate model. Pure so it's unit-testable."""
    return (
        "A reminder is scheduled to send to the user RIGHT NOW.\n\n"
        f"Reminder text: {reminder_text}\n"
        f"Cancel this reminder if: {cancel_if}\n\n"
        f"Current time: {now_str}\n"
        f"Live situation:\n{situation}\n\n"
        "Has the situation made this reminder moot (the user already did the "
        "thing, or it no longer applies)?\n"
        "- Reply exactly DROP to cancel it.\n"
        "- Reply exactly SEND to send it as written.\n"
        "- Reply 'SEND: <new text>' to send it with wording updated to the "
        "current situation.\n"
        "Reply with only that — no explanation."
    )


def parse_gate_verdict(reply: str) -> GateVerdict:
    """Parse the gate model's reply. Unrecognized/empty -> SEND (fail-open:
    a possibly-stale reminder beats silently swallowing a real one). Pure."""
    line = (reply or "").strip()
    if not line:
        return GateVerdict(drop=False, text=None)
    first = line.splitlines()[0].strip()
    upper = first.upper()
    if upper.startswith("DROP"):
        return GateVerdict(drop=True, text=None)
    if upper.startswith("SEND"):
        rest = first[4:].lstrip()
        if rest.startswith(":"):
            new = rest[1:].strip()
            return GateVerdict(drop=False, text=new or None)
        return GateVerdict(drop=False, text=None)
    return GateVerdict(drop=False, text=None)


async def _gate_reminder(
    settings: HalOrchestratorConfig,
    http_client: httpx.AsyncClient,
    session: AsyncSession,
    reminder: HalReminder,
    now: datetime,
) -> GateVerdict | None:
    """Re-evaluate a reminder's `cancel_if` against live state via the cheap
    background model. Returns None on model failure (caller fails open = send).

    The situation the model judges over: the baby forecast (when the silo has
    a family) plus the silo's RECENT CONVERSATION — the richest live signal.
    A parent texting "717 asleep" or "let's skip it tonight" is exactly what
    should kill a pending awake-time reminder, and only the model can weigh
    that; there is deliberately no hard-coded cancellation rule."""
    from hal_orchestrator.services.baby import (
        as_pairs,
        forecast_next,
        format_forecast,
        get_family_for_silo,
        load_events,
    )
    from hal_orchestrator.services.gemini import call_gemini

    situation_parts: list[str] = []
    now_str = now.astimezone(timezone.utc).strftime("%a %b %-d %-I:%M %p UTC")

    family = await get_family_for_silo(session, reminder.phone)
    if family is not None:
        tz = ZoneInfo(family.timezone)
        now_str = now.astimezone(tz).strftime("%a %b %-d %-I:%M %p")
        events = as_pairs(
            await load_events(session, family.id, since=now - timedelta(days=14))
        )
        if events:
            forecast = forecast_next(events, tz, now)
            situation_parts.append(format_forecast(forecast, tz, family.baby_name))

    # Recent conversation in the reminder's silo (best-effort). Newest last so
    # the model reads it chronologically.
    try:
        from hal_orchestrator.services.history_search import search_history

        recent = await search_history(session, reminder.phone, query="", limit=8)
        if recent:
            lines = [
                f"[{(r.get('at') or '')[:16]}] {r['role']}: {r['content'][:200]}"
                for r in reversed(recent)
            ]
            situation_parts.append(
                "Recent conversation in this chat (oldest first):\n"
                + "\n".join(lines)
            )
    except Exception:
        log.exception("reminder.gate_history_failed", reminder_id=str(reminder.id))

    situation = "\n".join(situation_parts) or "(no extra context available)"
    prompt = build_gate_prompt(reminder.text, reminder.cancel_if, situation, now_str)

    resp = await call_gemini(
        client=http_client,
        settings=settings,
        history=[{"role": "user", "parts": [{"text": prompt}]}],
        tools=None,
        system=GATE_SYSTEM,
        model=settings.gemini_background_model,
    )
    if not resp:
        return None

    parts = (resp.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    raw = "".join(p.get("text", "") for p in parts)
    verdict = parse_gate_verdict(raw)
    log.info(
        "reminder.gate",
        reminder_id=str(reminder.id),
        drop=verdict.drop,
        reworded=bool(verdict.text),
    )
    return verdict


async def _send_reminder_via_bridge(
    settings: HalOrchestratorConfig,
    http_client: httpx.AsyncClient,
    session: AsyncSession,
    reminder: HalReminder,
) -> None:
    """Queue a reminder message in the outbox for the bridge to pick up, and
    persist the send into the silo's conversation + archive. Before this,
    reminder sends were invisible to HAL itself (and to anyone auditing the
    transcript): the model would re-promise or re-send nudges it had no record
    of, and a fired reminder couldn't inform later turns.

    Called AFTER the reminder's own transaction committed. The history write
    runs in its own short transaction with a lock_timeout: load_conversation
    takes the silo's hal_conversations row FOR UPDATE, and an in-flight
    message turn holds that lock for its whole (possibly multi-minute) model
    loop — the checker must skip the nicety rather than stall every other
    silo's due reminders behind one busy chat."""
    import hal_orchestrator.state as state

    message = f"Reminder: {reminder.text}"
    await state.outbox.put({"to": reminder.phone, "text": message})
    state.mark_proactive_send(reminder.phone)
    log.info(
        "reminder.queued",
        phone=reminder.phone,
        text=reminder.text[:50] if state.settings.log_message_content else None,
        text_len=len(reminder.text or ""),
    )

    # Best-effort persistence — a logging failure must never block the send
    # (the outbox already has it) and never poison the checker's session.
    try:
        from sqlalchemy import text as sa_text

        from hal_orchestrator.prompts.system import USER_TZ
        from hal_orchestrator.services.conversation import (
            load_conversation,
            save_conversation,
        )
        from hal_orchestrator.services.history_search import archive_turn

        # Give up fast if the conversation row is locked by a live turn.
        await session.execute(sa_text("SET LOCAL lock_timeout = '3000'"))

        stamp = datetime.now(USER_TZ).strftime("%a %b %-d %-I:%M %p")
        history = await load_conversation(session, reminder.phone)
        history.append(
            {
                "role": "user",
                "parts": [{"text": f"[{stamp}] [scheduled reminder fired — you sent:]"}],
            }
        )
        history.append({"role": "model", "parts": [{"text": message}]})
        await save_conversation(
            session,
            reminder.phone,
            history,
            max_turns=settings.max_conversation_turns,
        )
        await archive_turn(session, reminder.phone, "assistant", message)
        await session.commit()
    except Exception:
        log.warning("reminder.log_send_skipped", reminder_id=str(reminder.id))
        try:
            await session.rollback()
        except Exception:
            log.exception("reminder.log_rollback_failed", reminder_id=str(reminder.id))


def _next_occurrence(current: datetime, recurrence: str) -> datetime | None:
    """Calculate the next occurrence for a recurring reminder."""
    if recurrence == "daily":
        return current + timedelta(days=1)
    elif recurrence == "weekly":
        return current + timedelta(weeks=1)
    elif recurrence == "monthly":
        # Approximate: add 30 days
        return current + timedelta(days=30)
    return None
