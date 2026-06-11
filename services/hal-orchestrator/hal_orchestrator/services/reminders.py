"""Reminder CRUD + background checker (Postgres)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import HalOrchestratorConfig
from ag_db.models import HalReminder
from ag_db.session import get_session

log = structlog.get_logger()


async def create_reminder(
    session: AsyncSession,
    phone: str,
    text: str,
    due_at: datetime,
    recurrence: str | None = None,
    sender_phone: str | None = None,
    is_group: bool = False,
    group_name: str | None = None,
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
    )
    session.add(reminder)
    await session.flush()

    log.info("reminder.created", phone=phone, text=text[:50], due_at=str(due_at))
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
                await _send_reminder_via_bridge(settings, http_client, reminder)
                reminder.sent = True

                # Handle recurrence
                if reminder.recurrence:
                    next_due = _next_occurrence(reminder.due_at, reminder.recurrence)
                    if next_due:
                        new_reminder = HalReminder(
                            phone=reminder.phone,
                            text=reminder.text,
                            due_at=next_due,
                            recurrence=reminder.recurrence,
                            sender_phone=reminder.sender_phone,
                            is_group=reminder.is_group,
                            group_name=reminder.group_name,
                        )
                        session.add(new_reminder)

                await session.flush()
            except Exception:
                log.exception(
                    "reminder.send_failed",
                    reminder_id=str(reminder.id),
                    phone=reminder.phone,
                )

        await session.commit()


async def _send_reminder_via_bridge(
    settings: HalOrchestratorConfig,
    http_client: httpx.AsyncClient,
    reminder: HalReminder,
) -> None:
    """Queue a reminder message in the outbox for the bridge to pick up."""
    import hal_orchestrator.state as state

    message = f"Reminder: {reminder.text}"
    await state.outbox.put({"to": reminder.phone, "text": message})
    log.info("reminder.queued", phone=reminder.phone, text=reminder.text[:50])


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
