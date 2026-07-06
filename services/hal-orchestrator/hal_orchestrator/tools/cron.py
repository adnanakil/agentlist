"""schedule tool — agentic scheduled tasks (run an agent turn on a schedule).

Different from set_reminder (which just re-sends static text). Use this when the
user wants HAL to DO something on a schedule and deliver the result, e.g. "every
weekday at 8am text me my morning brief", "summarize my unread email at 6pm".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from hal_orchestrator.services.cron import (
    RECURRENCES,
    create_cron,
    delete_cron,
    list_cron,
    reschedule,
)
from hal_orchestrator.tools.registry import ToolContext


async def tool_schedule(args: dict, ctx: ToolContext) -> str:
    action = args.get("action", "")

    if action == "create":
        prompt = args.get("prompt") or args.get("task") or ""
        due_str = args.get("due_time", "")
        recur = (args.get("recur") or "once").lower()
        if not prompt or not due_str:
            return "Error: 'prompt' (the task to run) and 'due_time' are required."
        if recur not in RECURRENCES:
            return f"Error: recur must be one of {', '.join(sorted(RECURRENCES))}."
        try:
            due = datetime.fromisoformat(due_str)
        except ValueError:
            return f"Error: invalid due_time '{due_str}'. Use ISO, e.g. 2026-06-11T08:00:00-04:00."
        from hal_orchestrator.prompts.system import resolve_tz
        from hal_orchestrator.services.profiles import get_profile

        try:
            user_tz = resolve_tz(await get_profile(ctx.session, ctx.phone))
        except Exception:
            user_tz = resolve_tz(None)
        offset_note = ""
        if due.tzinfo is None:
            # A bare time means the USER'S local time, not UTC — otherwise
            # "brief me at 8am" fires at 8am UTC (4am ET). Same rule as
            # set_reminder.
            due = due.replace(tzinfo=user_tz)
        elif due.utcoffset() != due.astimezone(user_tz).utcoffset():
            # Explicit non-local offset: legit for true UTC math, but the live
            # failure mode is a wall-clock slip (local time sent with Z).
            offset_note = (
                " ⚠️ You passed a non-local UTC offset. If the user asked for "
                "a LOCAL wall-clock time and the local time shown here is not "
                "what they said, delete this job and recreate it with a naive "
                "local ISO time (no offset)."
            )
        due = due.astimezone(timezone.utc)

        # Past-due guard (same as set_reminder): a past one-shot runs
        # instantly — almost always an AM/PM/date slip; recurring rolls to
        # the next occurrence.
        now = datetime.now(timezone.utc)
        if due <= now - timedelta(minutes=1):
            if recur != "once":
                rolled = reschedule(due, recur, now)
                if rolled:
                    due = rolled
            else:
                return (
                    f"Error: due_time {due.isoformat()} is in the PAST "
                    f"(now {now.isoformat()} UTC). Likely an AM/PM or date "
                    "slip — call current_time, recompute, and try again."
                )

        job = await create_cron(
            ctx.session,
            phone=ctx.phone,
            prompt=prompt,
            next_run_at=due,
            recurrence=recur,
            is_group=ctx.is_group,
            chat_id=ctx.chat_id,
            sender_phone=ctx.sender_phone,
        )
        local = due.astimezone(user_tz)
        return (
            f"Scheduled task ({recur}): \"{prompt[:80]}\" — next run "
            f"{local:%a %b %-d, %-I:%M %p} ({user_tz}). Confirm THIS local "
            f"time to the user. [id: {job.id}]{offset_note}"
        )

    if action == "list":
        jobs = await list_cron(ctx.session, ctx.phone)
        if not jobs:
            return "No scheduled tasks."
        return "Scheduled tasks:\n" + "\n".join(
            f"- [id: {j.id}] ({j.recurrence}) next {j.next_run_at.isoformat()}: {j.prompt[:80]}"
            for j in jobs
        )

    if action == "delete":
        jid = args.get("job_id", "")
        if not jid:
            return "Error: job_id is required."
        ok = await delete_cron(ctx.session, jid, ctx.phone)
        return "Scheduled task deleted." if ok else "Task not found."

    return f"Unknown schedule action: {action}. Use: create, list, delete."
