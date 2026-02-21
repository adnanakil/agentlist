"""web_search and web_fetch tools — DuckDuckGo search + page fetching."""

from __future__ import annotations

import re

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"


async def tool_web_search(args: dict, ctx: ToolContext) -> str:
    """Search the web using DuckDuckGo HTML interface."""
    query = args.get("query", "")
    if not query:
        return "Error: query is required"

    try:
        resp = await ctx.http_client.post(
            DUCKDUCKGO_HTML_URL,
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        html = resp.text

        # Extract results from DuckDuckGo HTML
        results = []
        # Pattern: <a class="result__a" href="...">title</a> ... <a class="result__snippet">snippet</a>
        snippets = re.findall(
            r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )

        for url, title, snippet in snippets[:5]:
            title = re.sub(r"<[^>]+>", "", title).strip()
            snippet = re.sub(r"<[^>]+>", "", snippet).strip()
            if title:
                results.append(f"{title}\n{snippet}\n{url}")

        if not results:
            return f"No results found for '{query}'."

        return "\n\n".join(results)

    except Exception as exc:
        log.exception("web_search.error", query=query)
        return f"Search error: {exc}"


async def tool_web_fetch(args: dict, ctx: ToolContext) -> str:
    """Fetch and extract text content from a URL."""
    url = args.get("url", "")
    if not url:
        return "Error: url is required"

    try:
        resp = await ctx.http_client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
            timeout=20,
        )

        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            # Strip HTML tags, extract text
            text = re.sub(r"<script[^>]*>.*?</script>", "", resp.text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            # Truncate to ~8000 chars
            if len(text) > 8000:
                text = text[:8000] + "... (truncated)"
            return text
        else:
            return resp.text[:8000]

    except Exception as exc:
        log.exception("web_fetch.error", url=url)
        return f"Fetch error: {exc}"
