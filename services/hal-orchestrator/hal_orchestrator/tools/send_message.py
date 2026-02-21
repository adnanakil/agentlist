"""send_message tool — sends iMessage via the bridge."""

from __future__ import annotations

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()


async def tool_send_message(args: dict, ctx: ToolContext) -> str:
    """Send an iMessage through the bridge."""
    to = args.get("to", "")
    text = args.get("text", "")

    if not to or not text:
        return "Error: 'to' and 'text' are required"

    if not ctx.settings.hal_bridge_url:
        return "Error: bridge URL not configured"

    try:
        resp = await ctx.http_client.post(
            f"{ctx.settings.hal_bridge_url}/send",
            json={"to": to, "text": text},
            headers={"Authorization": f"Bearer {ctx.settings.hal_bridge_secret}"},
            timeout=30,
        )

        if resp.status_code == 200:
            log.info("send_message.sent", to=to, text=text[:50])
            return f"Message sent to {to}: {text}"
        else:
            log.error("send_message.failed", status=resp.status_code, body=resp.text[:200])
            return f"Failed to send message (status {resp.status_code})"

    except Exception as exc:
        log.exception("send_message.error", to=to)
        return f"Send error: {exc}"
