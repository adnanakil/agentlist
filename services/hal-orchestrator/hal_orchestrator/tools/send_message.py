"""send_message tool — queues messages for the bridge to send."""

from __future__ import annotations

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()


async def tool_send_message(args: dict, ctx: ToolContext) -> str:
    """Queue an iMessage to be sent by the bridge.

    Instead of calling back to the bridge (which isn't publicly reachable),
    we accumulate side messages in the ToolContext. The message route returns
    them in the response so the bridge can send them.
    """
    to = args.get("to", "")
    text = args.get("text", "")

    if not to or not text:
        return "Error: 'to' and 'text' are required"

    ctx.side_messages.append({"to": to, "text": text})
    log.info("send_message.queued", to=to, text=text[:50])
    return f"Message queued for {to}: {text}"
