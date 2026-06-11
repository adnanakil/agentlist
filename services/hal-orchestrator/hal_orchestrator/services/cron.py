"""Agentic cron — scheduled full agent turns.

At a job's time, HAL runs a complete agent turn on the job's `prompt` in the
silo's context and delivers the result. Implementation reuses the ENTIRE message
pipeline by POSTing the prompt to this service's own /api/message endpoint
(so a scheduled task behaves exactly like an inbound message — no duplicated
agent loop, no risk to the live path), then enqueues the reply to the outbox the
bridge drains. Distinct from HalReminder, which just re-sends static text.
"""

from __future__ import annotations

import asyncio
import calendar
import os
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import HalOrchestratorConfig
from ag_db.models import HalCronJob
from ag_db.session import get_session

log = structlog.get_logger()

RECURRENCES = {"once", "daily", "weekdays", "weekly", "monthly"}


# --------------------------------------------------------------------------- #
# Scheduling math
# --------------------------------------------------------------------------- #


def _add_month(dt: datetime) -> datetime:
    y, m = (dt.year + 1, 1) if dt.month == 12 else (dt.year, dt.month + 1)
    day = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=day)


def reschedule(scheduled: datetime, recurrence: str, now: datetime) -> datetime | None:
    """Next fire time after `scheduled`, advancing past `now` so a late checker
    doesn't immediately re-fire. None for one-offs."""
    if recurrence == "once":
        return None
    nxt = scheduled
    for _ in range(400):
        if recurrence == "daily":
            nxt = nxt + timedelta(days=1)
        elif recurrence == "weekly":
            nxt = nxt + timedelta(days=7)
        elif recurrence == "weekdays":
            nxt = nxt + timedelta(days=1)
            while nxt.weekday() >= 5:
                nxt = nxt + timedelta(days=1)
        elif recurrence == "monthly":
            nxt = _add_month(nxt)
        else:
            return None
        if nxt > now:
            return nxt
    return nxt


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #


async def create_cron(
    session: AsyncSession,
    phone: str,
    prompt: str,
    next_run_at: datetime,
    recurrence: str = "once",
    is_group: bool = False,
    chat_id: str | None = None,
    sender_phone: str | None = None,
) -> HalCronJob:
    job = HalCronJob(
        phone=phone,
        prompt=prompt,
        recurrence=recurrence if recurrence in RECURRENCES else "once",
        next_run_at=next_run_at,
        is_group=is_group,
        chat_id=chat_id,
        sender_phone=sender_phone,
    )
    session.add(job)
    await session.flush()
    log.info("cron.created", phone=phone, recurrence=job.recurrence, prompt=prompt[:60])
    return job


async def list_cron(session: AsyncSession, phone: str) -> list[HalCronJob]:
    stmt = (
        select(HalCronJob)
        .where(HalCronJob.phone == phone, HalCronJob.active == True)  # noqa: E712
        .order_by(HalCronJob.next_run_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def delete_cron(session: AsyncSession, job_id: str, phone: str) -> bool:
    from uuid import UUID

    try:
        uid = UUID(job_id)
    except ValueError:
        return False
    stmt = select(HalCronJob).where(HalCronJob.id == uid, HalCronJob.phone == phone)
    job = (await session.execute(stmt)).scalar_one_or_none()
    if job is None:
        return False
    await session.delete(job)
    await session.flush()
    return True


# --------------------------------------------------------------------------- #
# Background checker
# --------------------------------------------------------------------------- #


async def run_cron_checker(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    log.info("cron_checker.started")
    while True:
        try:
            await asyncio.sleep(settings.reminder_check_interval_seconds)
            await _check_and_run(settings, http)
        except asyncio.CancelledError:
            log.info("cron_checker.cancelled")
            raise
        except Exception:
            log.exception("cron_checker.error")
            await asyncio.sleep(10)


async def _check_and_run(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient
) -> None:
    now = datetime.now(timezone.utc)
    async for session in get_session():
        stmt = (
            select(HalCronJob)
            .where(HalCronJob.active == True, HalCronJob.next_run_at <= now)  # noqa: E712
            .limit(20)
        )
        due = (await session.execute(stmt)).scalars().all()
        for job in due:
            try:
                await _run_job(settings, http, job)
                job.last_status = "ok"
            except Exception as exc:
                log.exception("cron.run_failed", job_id=str(job.id))
                job.last_status = f"error: {str(exc)[:24]}"
            job.last_run_at = now
            nxt = reschedule(job.next_run_at, job.recurrence, now)
            if nxt is None:
                job.active = False
            else:
                job.next_run_at = nxt
            await session.flush()
        await session.commit()


async def _run_job(
    settings: HalOrchestratorConfig, http: httpx.AsyncClient, job: HalCronJob
) -> None:
    """Run the job's prompt through the full agent pipeline (internal call),
    then enqueue the reply (+ any side messages) to the outbox."""
    import hal_orchestrator.state as state

    port = os.environ.get("PORT", "8005")
    url = f"http://127.0.0.1:{port}/api/message"
    payload: dict = {
        "phone": job.sender_phone or job.phone,
        "text": job.prompt,
        "is_group": job.is_group,
    }
    if job.is_group and job.chat_id:
        payload["chat_id"] = job.chat_id

    resp = await http.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {settings.hal_bridge_secret}"},
        timeout=300.0,
    )
    resp.raise_for_status()
    data = resp.json()

    to = job.chat_id if (job.is_group and job.chat_id) else job.phone
    reply = (data.get("reply") or "").strip()
    if reply:
        await state.outbox.put({"to": to, "text": reply})
        log.info("cron.delivered", job_id=str(job.id), to=to, chars=len(reply))
    for sm in data.get("side_messages", []):
        if sm.get("to") and sm.get("text"):
            await state.outbox.put({"to": sm["to"], "text": sm["text"]})
