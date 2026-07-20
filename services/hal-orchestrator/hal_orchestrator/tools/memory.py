"""memory tool — wraps services/memory.py for per-user memory."""

from __future__ import annotations

import re

from hal_orchestrator.services.memory import list_memories, recall, remember
from hal_orchestrator.tools.registry import ToolContext

# Timestamped baby-care events belong in the structured baby log, not memory.
# Heuristic: mentions the baby + a care verb + an explicit clock time, and is
# NOT a durable rule ("schedule", "whenever", ...). Soft net behind the system
# prompt, which already directs baby events to the baby tool.
_CARE_VERBS = re.compile(
    r"\b(fed|ate|eating|feed|nap|napping|asleep|sleep|slept|woke|wake|bedtime)\b",
    re.I,
)
_CLOCK_TIME = re.compile(r"\d{1,2}:\d{2}\s*(am|pm)?|\d{1,2}\s*(am|pm)\b", re.I)
_RULE_WORDS = re.compile(r"\b(rule|schedule|whenever|always|every|usually|routine)\b", re.I)


def _looks_like_baby_event(content: str, baby_name: str) -> bool:
    return (
        baby_name.lower() in content.lower()
        and _CARE_VERBS.search(content) is not None
        and _CLOCK_TIME.search(content) is not None
        and _RULE_WORDS.search(content) is None
    )


async def tool_memory(args: dict, ctx: ToolContext) -> str:
    """Handle memory actions: remember, recall, list."""
    action = args.get("action", "")
    content = args.get("content", "")

    if action == "remember":
        if not content:
            return "Error: content is required to remember something"
        from hal_orchestrator.services.baby import get_family_for_silo

        family = await get_family_for_silo(ctx.session, ctx.phone)
        if family and _looks_like_baby_event(content, family.baby_name):
            return (
                "Not saved: this is a baby care event, which belongs in the "
                "structured baby log. Use baby(action=log, kind=feed|nap_start|"
                "wake|bedtime, time=<ISO>) instead."
            )
        return await remember(
            ctx.session, ctx.phone, content, ctx.http_client, ctx.settings
        )

    elif action == "recall":
        if not content:
            return "Error: content is required to search memories"
        since = None
        if ctx.is_group:
            from hal_orchestrator.services.membership import group_memory_floor

            since = await group_memory_floor(ctx.session, ctx.phone, ctx.sender_phone)
        return await recall(ctx.session, ctx.phone, content, since=since)

    elif action == "list":
        since = None
        if ctx.is_group:
            from hal_orchestrator.services.membership import group_memory_floor

            since = await group_memory_floor(ctx.session, ctx.phone, ctx.sender_phone)
        return await list_memories(ctx.session, ctx.phone, since=since)

    else:
        return f"Unknown memory action: {action}. Use: remember, recall, or list"
