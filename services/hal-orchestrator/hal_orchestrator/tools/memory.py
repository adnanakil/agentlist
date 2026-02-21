"""memory tool — wraps services/memory.py for per-user memory."""

from __future__ import annotations

from hal_orchestrator.services.memory import list_memories, recall, remember
from hal_orchestrator.tools.registry import ToolContext


async def tool_memory(args: dict, ctx: ToolContext) -> str:
    """Handle memory actions: remember, recall, list."""
    action = args.get("action", "")
    content = args.get("content", "")

    if action == "remember":
        if not content:
            return "Error: content is required to remember something"
        return await remember(ctx.session, ctx.phone, content)

    elif action == "recall":
        if not content:
            return "Error: content is required to search memories"
        return await recall(ctx.session, ctx.phone, content)

    elif action == "list":
        return await list_memories(ctx.session, ctx.phone)

    else:
        return f"Unknown memory action: {action}. Use: remember, recall, or list"
