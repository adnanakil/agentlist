"""Browser tool — calls the browser service for web content extraction."""

from __future__ import annotations

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()


async def tool_browser(args: dict, ctx: ToolContext) -> str:
    """Browse the web using the browser service (Playwright + Chromium)."""
    url = args.get("url", "")
    if not url:
        return "Error: url is required"

    action = args.get("action", "extract")
    payload: dict = {"url": url, "action": action}

    # Pass optional args
    for key in ("selector", "text", "javascript"):
        if args.get(key):
            payload[key] = args[key]

    browser_url = ctx.settings.browser_service_url
    if not browser_url:
        return "Error: browser service not configured (BROWSER_SERVICE_URL not set)"

    log.info("tool.browser", url=url, action=action)

    try:
        resp = await ctx.http_client.post(
            f"{browser_url}/",
            json={"input": payload},
            timeout=90.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        log.error("tool.browser.request_failed", error=str(exc))
        return f"Browser error: {exc}"

    data = resp.json()
    if "error" in data:
        return f"Browser error: {data['error']}"

    output = data.get("output", data)

    # Format result for Gemini consumption
    parts: list[str] = []

    if output.get("title"):
        parts.append(f"Title: {output['title']}")
    if output.get("channel"):
        parts.append(f"Channel: {output['channel']}")
    if output.get("author"):
        parts.append(f"Author: {output['author']}")
    if output.get("type"):
        parts.append(f"Type: {output['type']}")
    if output.get("url"):
        parts.append(f"URL: {output['url']}")

    if output.get("transcript"):
        parts.append(f"\nTranscript ({output.get('transcript_source', 'unknown')}):")
        parts.append(output["transcript"])
    elif output.get("transcript_error"):
        parts.append(f"\nTranscript: {output['transcript_error']}")

    if output.get("description"):
        parts.append(f"\nDescription: {output['description']}")

    if output.get("content"):
        parts.append(f"\nContent:\n{output['content']}")

    if output.get("screenshot_base64"):
        parts.append("\n[Screenshot captured — base64 data available]")

    if output.get("links"):
        links_text = "\n".join(f"- {l['text']}: {l['href']}" for l in output["links"][:20])
        parts.append(f"\nLinks:\n{links_text}")

    if output.get("result") is not None:
        parts.append(f"\nResult: {output['result']}")

    return "\n".join(parts) if parts else str(output)
