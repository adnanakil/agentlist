"""Tool dispatcher — routes tool calls to implementations."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import HalOrchestratorConfig

log = structlog.get_logger()


@dataclass
class ToolContext:
    """Context passed to every tool handler.

    `phone` is the SILO key, not necessarily a phone number: the user's
    normalized handle in 1:1 chats, the group chat id in group chats. Tools
    that persist state (memory, profile, reminders, skills) key off it, which
    is what keeps each user's data isolated and gives groups a shared space
    separate from any member's personal data. Use `sender_phone` when you need
    the actual person speaking (e.g. trip votes).
    """

    phone: str
    session: AsyncSession
    settings: HalOrchestratorConfig
    http_client: httpx.AsyncClient
    chat_id: str | None = None  # Group chat identifier
    sender_phone: str | None = None  # Actual sender (differs from phone in groups)
    is_group: bool = False
    side_messages: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)  # [{mime_type, data}]
    result_images: list[dict] = field(default_factory=list)  # [{mime_type, data, ext}]


# Stubbed tools — return "not yet available"
STUBBED_TOOLS = {
    "vault",
    "connect_account",
    "bash",
    "manage_agents",
    "events",
}


async def execute_tool(
    name: str,
    args: dict,
    ctx: ToolContext,
) -> str:
    """Execute a tool by name and return the string result."""
    from hal_orchestrator.tools.baby import tool_baby
    from hal_orchestrator.tools.browser import tool_browser
    from hal_orchestrator.tools.contacts import tool_contacts
    from hal_orchestrator.tools.cron import tool_schedule
    from hal_orchestrator.tools.current_time import tool_current_time
    from hal_orchestrator.tools.delegate import tool_delegate
    from hal_orchestrator.tools.helpful import tool_helpful
    from hal_orchestrator.tools.history import tool_recall_history
    from hal_orchestrator.tools.resy import tool_resy
    from hal_orchestrator.tools.google import (
        tool_google_auth,
        tool_google_calendar,
        tool_google_gmail,
    )
    from hal_orchestrator.tools.image_edit import tool_image_edit
    from hal_orchestrator.tools.memory import tool_memory
    from hal_orchestrator.tools.profile import tool_profile
    from hal_orchestrator.tools.reminders import tool_set_reminder
    from hal_orchestrator.tools.send_message import tool_send_message
    from hal_orchestrator.tools.skill import tool_skill
    from hal_orchestrator.tools.sports_score import tool_sports_score
    from hal_orchestrator.tools.travel_time import tool_travel_time
    from hal_orchestrator.tools.watch import tool_watch
    from hal_orchestrator.tools.weather import tool_weather
    from hal_orchestrator.tools.stubs import tool_stub
    from hal_orchestrator.tools.trips import tool_trip
    from hal_orchestrator.tools.web_search import tool_web_fetch, tool_web_search

    log.info("tool.execute", tool=name, args_keys=list(args.keys()), phone=ctx.phone)

    if name in STUBBED_TOOLS:
        # Unmet demand — feeds the nightly reflection's feature proposals.
        try:
            from hal_orchestrator.services.friction import KIND_STUB, log_friction

            log_friction(ctx.session, ctx.phone, KIND_STUB, name)
        except Exception:
            pass
        return tool_stub(name)

    handlers = {
        "current_time": lambda: tool_current_time(ctx),
        "web_search": lambda: tool_web_search(args, ctx),
        "web_fetch": lambda: tool_web_fetch(args, ctx),
        "get_weather": lambda: tool_weather(args, ctx),
        "travel_time": lambda: tool_travel_time(args, ctx),
        "send_message": lambda: tool_send_message(args, ctx),
        "baby": lambda: tool_baby(args, ctx),
        "memory": lambda: tool_memory(args, ctx),
        "profile": lambda: tool_profile(args, ctx),
        "contacts": lambda: tool_contacts(args, ctx),
        "set_reminder": lambda: tool_set_reminder(args, ctx),
        "delegate": lambda: tool_delegate(args, ctx),
        "browser": lambda: tool_browser(args, ctx),
        "image_edit": lambda: tool_image_edit(args, ctx),
        "trip": lambda: tool_trip(args, ctx),
        "skill": lambda: tool_skill(args, ctx),
        "google_auth": lambda: tool_google_auth(args, ctx),
        "google_calendar": lambda: tool_google_calendar(args, ctx),
        "google_gmail": lambda: tool_google_gmail(args, ctx),
        "recall_history": lambda: tool_recall_history(args, ctx),
        "schedule": lambda: tool_schedule(args, ctx),
        "resy": lambda: tool_resy(args, ctx),
        "watch": lambda: tool_watch(args, ctx),
        "sports_score": lambda: tool_sports_score(args, ctx),
        "helpful_mode": lambda: tool_helpful(args, ctx),
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
        try:
            from hal_orchestrator.services.friction import KIND_TOOL_ERROR, log_friction

            log_friction(ctx.session, ctx.phone, KIND_TOOL_ERROR, f"{name}: {exc}")
        except Exception:
            pass
        return f"Tool error ({name}): {exc}"
