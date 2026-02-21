"""Tool dispatcher — routes tool calls to implementations."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import HalOrchestratorConfig

log = structlog.get_logger()


@dataclass
class ToolContext:
    """Context passed to every tool handler."""

    phone: str
    session: AsyncSession
    settings: HalOrchestratorConfig
    http_client: httpx.AsyncClient


# Stubbed tools — return "not yet available"
STUBBED_TOOLS = {
    "google_auth",
    "google_calendar",
    "google_gmail",
    "vault",
    "connect_account",
    "browser",
    "bash",
    "resy",
    "manage_agents",
    "events",
}


async def execute_tool(
    name: str,
    args: dict,
    ctx: ToolContext,
) -> str:
    """Execute a tool by name and return the string result."""
    from hal_orchestrator.tools.contacts import tool_contacts
    from hal_orchestrator.tools.current_time import tool_current_time
    from hal_orchestrator.tools.delegate import tool_delegate
    from hal_orchestrator.tools.memory import tool_memory
    from hal_orchestrator.tools.reminders import tool_set_reminder
    from hal_orchestrator.tools.send_message import tool_send_message
    from hal_orchestrator.tools.stubs import tool_stub
    from hal_orchestrator.tools.web_search import tool_web_fetch, tool_web_search

    log.info("tool.execute", tool=name, args_keys=list(args.keys()), phone=ctx.phone)

    if name in STUBBED_TOOLS:
        return tool_stub(name)

    handlers = {
        "current_time": lambda: tool_current_time(),
        "web_search": lambda: tool_web_search(args, ctx),
        "web_fetch": lambda: tool_web_fetch(args, ctx),
        "send_message": lambda: tool_send_message(args, ctx),
        "memory": lambda: tool_memory(args, ctx),
        "contacts": lambda: tool_contacts(args, ctx),
        "set_reminder": lambda: tool_set_reminder(args, ctx),
        "delegate": lambda: tool_delegate(args, ctx),
    }

    handler = handlers.get(name)
    if handler is None:
        return f"Unknown tool: {name}"

    try:
        result = handler()
        # Handlers may be async
        if hasattr(result, "__await__"):
            result = await result
        return str(result)
    except Exception as exc:
        log.exception("tool.error", tool=name, error=str(exc))
        return f"Tool error ({name}): {exc}"
