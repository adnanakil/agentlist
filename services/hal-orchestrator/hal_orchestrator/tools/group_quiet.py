"""group_quiet tool — persist a "butt out" in a group chat.

Before this, "keep it to yourself" / "stfu hal" changed nothing durable: the
model apologized, then the very next status update re-tempted it (and on
2026-06-30 it re-interjected 90 minutes after being told to stfu). Now the
model calls this tool and the mute is enforced in CODE: the message route
force-silences every non-@Hal group message until the mute expires, so there
is no draft for temperature to leak. Explicit "Hal ..." mentions still get
through — the user can always summon HAL mid-mute.
"""

from __future__ import annotations

from hal_orchestrator.prompts.system import USER_TZ
from hal_orchestrator.services.identity import is_group_id
from hal_orchestrator.services.watched import muted_until, set_muted
from hal_orchestrator.tools.registry import ToolContext

DEFAULT_MUTE_DAYS = 3.0
MAX_MUTE_DAYS = 30.0


async def tool_group_quiet(args: dict, ctx: ToolContext) -> str:
    action = args.get("action", "")
    chat_id = ctx.chat_id or (ctx.phone if is_group_id(ctx.phone) else None)
    if not ctx.is_group or not chat_id:
        return (
            "group_quiet only applies in group chats — in a 1:1 the user can "
            "just tell you to stop and you should simply comply."
        )

    if action == "mute":
        try:
            days = float(args.get("days") or DEFAULT_MUTE_DAYS)
        except (TypeError, ValueError):
            days = DEFAULT_MUTE_DAYS
        days = max(0.25, min(days, MAX_MUTE_DAYS))
        until = await set_muted(ctx.session, chat_id, days)
        local = until.astimezone(USER_TZ)
        return (
            f"Muted in this group until {local:%a %b %-d, %-I:%M %p}. Until "
            "then you will ONLY see/answer messages that explicitly mention "
            "'Hal' — everything else is auto-silenced. Acknowledge in a few "
            "words at most (or not at all if you already did), then stop."
        )

    if action == "unmute":
        await set_muted(ctx.session, chat_id, None)
        return "Unmuted — normal group behavior (restraint rules still apply)."

    if action == "status":
        until = await muted_until(ctx.session, chat_id)
        if until is None:
            return "Not muted in this group."
        local = until.astimezone(USER_TZ)
        return f"Muted in this group until {local:%a %b %-d, %-I:%M %p}."

    return f"Unknown group_quiet action: {action}. Use: mute, unmute, or status."
