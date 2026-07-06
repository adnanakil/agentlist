"""set_reminder tool — wraps services/reminders.py."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from hal_orchestrator.services.reminders import (
    create_reminder,
    delete_reminder,
    list_reminders,
)
from hal_orchestrator.tools.registry import ToolContext


async def tool_set_reminder(args: dict, ctx: ToolContext) -> str:
    """Handle set_reminder actions: create, list, delete."""
    action = args.get("action", "")

    if action == "create":
        text = args.get("text", "")
        due_time_str = args.get("due_time", "")
        recur = args.get("recur")
        cancel_if = (args.get("cancel_if") or "").strip() or None

        if not text or not due_time_str:
            return "Error: 'text' and 'due_time' are required"

        try:
            due_at = datetime.fromisoformat(due_time_str)
        except ValueError:
            return f"Error: invalid due_time format: {due_time_str}. Use ISO format like 2026-02-10T09:00:00"
        from hal_orchestrator.prompts.system import resolve_tz
        from hal_orchestrator.services.profiles import get_profile

        try:
            user_tz = resolve_tz(await get_profile(ctx.session, ctx.phone))
        except Exception:
            # A profile read failure must not block the reminder; fall back to
            # the default zone (what resolve_tz returns for an empty profile).
            user_tz = resolve_tz(None)
        offset_note = ""
        if due_at.tzinfo is None:
            # A bare time means the USER'S local time, not UTC — otherwise a
            # naive "9am" is stored as 9am UTC (5am ET) and pings them at dawn.
            due_at = due_at.replace(tzinfo=user_tz)
        elif due_at.utcoffset() != due_at.astimezone(user_tz).utcoffset():
            # The model passed an explicit offset that isn't this chat's local
            # offset. Legit when it truly computed UTC — but the live failure
            # mode is a wall-clock slip ("7 PM" sent as 19:00Z → fired 3 PM
            # ET). Flag it loudly so the model verifies against user intent.
            offset_note = (
                " ⚠️ You passed a non-local UTC offset. If the user asked for "
                "a LOCAL wall-clock time and the local time shown here is not "
                "what they said, delete this reminder and recreate it with a "
                "naive local ISO time (no offset)."
            )
        due_at = due_at.astimezone(timezone.utc)

        # Past-due guard: a one-shot reminder in the past fires INSTANTLY,
        # which is never what anyone meant — it's almost always an AM/PM or
        # date slip in the computed ISO (seen live: "7:22 PM" said, 07:22
        # stored, pinged the user immediately). Make the model recompute.
        now = datetime.now(timezone.utc)
        if due_at <= now - timedelta(minutes=1):
            if recur:
                # Recurring ("every day at 8am" set after 8am): roll forward
                # to the next occurrence instead of erroring.
                from hal_orchestrator.services.cron import reschedule

                rolled = reschedule(due_at, recur, now)
                if rolled:
                    due_at = rolled
            else:
                return (
                    f"Error: due_time {due_at.isoformat()} is in the PAST "
                    f"(now {now.isoformat()} UTC). This is usually an AM/PM or "
                    "date slip — call current_time, recompute the intended "
                    "LOCAL time, and create the reminder again."
                )

        # Supersede check BEFORE creating: an unsent one-shot in the same
        # window about the same thing is almost always the version this one
        # replaces (a re-negotiated time). Auto-cancel near-duplicates so the
        # stale one can't fire; surface anything else nearby for the model to
        # judge.
        from hal_orchestrator.services.reminders import (
            find_nearby_pending,
            is_probable_duplicate,
        )

        superseded: list[str] = []
        nearby_notes: list[str] = []
        try:
            for other in await find_nearby_pending(ctx.session, ctx.phone, due_at):
                if is_probable_duplicate(text, other.text):
                    local_other = other.due_at.astimezone(user_tz)
                    await delete_reminder(ctx.session, str(other.id), ctx.phone)
                    superseded.append(f"'{other.text[:60]}' ({local_other:%-I:%M %p})")
                else:
                    local_other = other.due_at.astimezone(user_tz)
                    nearby_notes.append(
                        f"[id: {other.id}] '{other.text[:60]}' at {local_other:%-I:%M %p}"
                    )
        except Exception:
            superseded, nearby_notes = [], []

        result = await create_reminder(
            ctx.session,
            phone=ctx.phone,
            text=text,
            due_at=due_at,
            recurrence=recur,
            sender_phone=getattr(ctx, "sender_phone", None),
            is_group=bool(getattr(ctx, "is_group", False)),
            cancel_if=cancel_if,
        )
        local = due_at.astimezone(user_tz)
        reply = (
            f"Reminder set for {local:%a %b %-d, %-I:%M %p} ({user_tz}). "
            f"Confirm THIS local time to the user. {json.dumps(result)}"
            f"{offset_note}"
        )
        if superseded:
            reply += " Auto-cancelled superseded reminder(s): " + "; ".join(superseded)
        if nearby_notes:
            reply += (
                " Other pending reminders near this time (delete any this one "
                "replaces): " + "; ".join(nearby_notes)
            )
        return reply

    elif action == "list":
        reminders = await list_reminders(ctx.session, ctx.phone)
        if not reminders:
            return "No pending reminders."
        return "Pending reminders:\n" + "\n".join(
            f"- [id: {r['id']}] {r['text']} (due: {r['due_at']}"
            + (f", {r['recurrence']}" if r.get("recurrence") else "")
            + ")"
            for r in reminders
        )

    elif action == "delete":
        reminder_id = args.get("reminder_id", "")
        if not reminder_id:
            return "Error: reminder_id is required"
        deleted = await delete_reminder(ctx.session, reminder_id, ctx.phone)
        return "Reminder deleted." if deleted else "Reminder not found."

    else:
        return f"Unknown reminder action: {action}. Use: create, list, or delete"
