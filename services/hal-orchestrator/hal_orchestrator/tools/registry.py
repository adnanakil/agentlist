"""Tool dispatcher — routes tool calls to implementations."""

from __future__ import annotations

import asyncio
import importlib
import inspect
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
    # Ephemeral, bridge-supplied Find My location for the current speaker. It is
    # available only during this turn and is redacted before history persists.
    current_location: dict | None = None
    user_text: str = ""  # actual inbound text; never tool/web content
    message_id: str | None = None
    internal: bool = False


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
    from hal_orchestrator.services.action_policy import authorize_tool
    from hal_orchestrator.tools.specs import get_tool_spec
    from hal_orchestrator.tools.stubs import tool_stub

    log.info("tool.execute", tool=name, args_keys=list(args.keys()), phone=ctx.phone)

    if name in STUBBED_TOOLS:
        # Unmet demand — feeds the nightly reflection's feature proposals.
        try:
            from hal_orchestrator.services.friction import KIND_STUB, log_friction

            log_friction(ctx.session, ctx.phone, KIND_STUB, name)
        except Exception:
            pass
        return tool_stub(name)

    spec = get_tool_spec(name)
    if spec is None:
        return f"Unknown tool: {name}"

    try:
        blocked = await authorize_tool(spec, args, ctx)
        if blocked is not None:
            return blocked
        module_name, attr_name = spec.handler.split(":", 1)
        handler = getattr(importlib.import_module(module_name), attr_name)
        # current_time is the one legacy handler that accepts only ctx.
        result = handler(ctx) if name == "current_time" else handler(args, ctx)
        if inspect.isawaitable(result):
            timeout = spec.timeout_seconds or ctx.settings.tool_timeout_seconds
            async with asyncio.timeout(timeout):
                result = await result
        return str(result)
    except TimeoutError:
        log.warning("tool.timeout", tool=name, seconds=ctx.settings.tool_timeout_seconds)
        return f"Tool error ({name}): timed out"
    except Exception as exc:
        log.exception("tool.error", tool=name, error=str(exc))
        try:
            from hal_orchestrator.services.friction import KIND_TOOL_ERROR, log_friction

            log_friction(ctx.session, ctx.phone, KIND_TOOL_ERROR, f"{name}: {exc}")
        except Exception:
            pass
        return f"Tool error ({name}): {exc}"
