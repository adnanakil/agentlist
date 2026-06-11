"""schedule tool — agentic scheduled tasks (run an agent turn on a schedule).

Different from set_reminder (which just re-sends static text). Use this when the
user wants HAL to DO something on a schedule and deliver the result, e.g. "every
weekday at 8am text me my morning brief", "summarize my unread email at 6pm".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from hal_orchestrator.services.cron import (
    RECURRENCES,
    create_cron,
    delete_cron,
    list_cron,
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
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
        except ValueError:
            return f"Error: invalid due_time '{due_str}'. Use ISO, e.g. 2026-06-11T08:00:00-04:00."

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
        return (
            f"Scheduled task ({recur}): \"{prompt[:80]}\" — next run "
            f"{due.isoformat()}. [id: {job.id}]"
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
