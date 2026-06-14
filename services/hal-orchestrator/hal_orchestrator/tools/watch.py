"""watch tool — the agent-facing notify-when-condition primitive.

actions:
  create — start watching; HAL MUST call this whenever it promises to alert the
           user "if/when X happens". Silent until the condition is true.
  list   — show this silo's active watches.
  cancel — stop a watch (by job_id) or all of them ("stop watching").
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hal_orchestrator.services.watch import (
    cancel_all,
    create_watch,
    delete_watch,
    list_watch,
)
from hal_orchestrator.tools.registry import ToolContext

DEFAULT_EXPIRES_MIN = 360
MAX_EXPIRES_MIN = 24 * 60
DEFAULT_MAX_POLLS = 60
MIN_POLL_SECONDS = 90


async def tool_watch(args: dict, ctx: ToolContext) -> str:
    action = (args.get("action") or "").strip().lower()

    if action == "create":
        condition = (args.get("condition") or "").strip()
        if not condition:
            return "Error: 'condition' is required (what to watch for)."

        check_prompt = (args.get("check_prompt") or condition).strip()
        notify = (args.get("notify") or f"Heads up — {condition}").strip()

        try:
            poll_every = max(MIN_POLL_SECONDS, int(args.get("poll_every_sec") or 150))
        except (TypeError, ValueError):
            poll_every = 150
        try:
            expires_in = int(args.get("expires_in_min") or DEFAULT_EXPIRES_MIN)
        except (TypeError, ValueError):
            expires_in = DEFAULT_EXPIRES_MIN
        expires_in = max(1, min(MAX_EXPIRES_MIN, expires_in))
        try:
            max_polls = int(args.get("max_polls") or DEFAULT_MAX_POLLS)
        except (TypeError, ValueError):
            max_polls = DEFAULT_MAX_POLLS

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_in)
        watch, err = await create_watch(
            ctx.session,
            phone=ctx.phone,
            condition=condition,
            check_prompt=check_prompt,
            notify=notify,
            expires_at=expires_at,
            poll_every_seconds=poll_every,
            max_polls=max_polls,
            is_group=ctx.is_group,
            chat_id=ctx.chat_id,
            sender_phone=ctx.sender_phone,
        )
        if err:
            return err
        local_expiry = expires_at.strftime("%-I:%M %p UTC")
        return (
            f"Watching for: {condition}. I'll message you once it's true, and "
            f"stay quiet until then (checking ~every {poll_every // 60} min, "
            f"until ~{local_expiry}). [id: {watch.id}]"
        )

    if action == "list":
        watches = await list_watch(ctx.session, ctx.phone)
        if not watches:
            return "No active watches."
        return "Active watches:\n" + "\n".join(
            f"- [id: {w.id}] {w.condition} "
            f"(checked {w.polls_done}x, expires {w.expires_at:%-I:%M %p UTC})"
            for w in watches
        )

    if action == "cancel":
        job_id = (args.get("job_id") or "").strip()
        if not job_id:
            n = await cancel_all(ctx.session, ctx.phone)
            return f"Stopped {n} watch{'es' if n != 1 else ''}." if n else "No active watches."
        ok = await delete_watch(ctx.session, job_id, ctx.phone)
        return "Watch cancelled." if ok else "Watch not found."

    return f"Unknown watch action: {action}. Use: create, list, or cancel."
