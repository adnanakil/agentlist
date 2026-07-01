"""web_search and web_fetch tools — Brave API (when keyed) with DuckDuckGo
HTML-scrape fallback, + page fetching.

The failure-honesty rule: a blocked/erroring search must NEVER read as "no
results" — the model would then confidently tell the user nothing exists.
Unavailability is reported as its own distinct message so the model retries
or switches to browser/web_fetch instead.
"""

from __future__ import annotations

import re

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

SEARCH_UNAVAILABLE = (
    "SEARCH UNAVAILABLE (the search service errored or blocked the request — "
    "this is NOT 'no results'). Retry once, or use browser/web_fetch on a "
    "likely URL instead. Do not tell the user nothing exists."
)


async def _brave_search(query: str, ctx: ToolContext) -> str | None:
    """Brave Search API — reliable JSON. Returns rendered results, '' for a
    genuine empty result set, or None to signal 'fall back to DDG'."""
    key = getattr(ctx.settings, "brave_search_api_key", "")
    if not key:
        return None
    try:
        resp = await ctx.http_client.get(
            BRAVE_SEARCH_URL,
            params={"q": query, "count": 5},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning("web_search.brave_http", status=resp.status_code)
            return None
        items = (resp.json().get("web") or {}).get("results") or []
        results = []
        for it in items[:5]:
            title = (it.get("title") or "").strip()
            desc = re.sub(r"<[^>]+>", "", it.get("description") or "").strip()
            if title:
                results.append(f"{title}\n{desc}\n{it.get('url', '')}")
        return "\n\n".join(results)
    except Exception:
        log.exception("web_search.brave_error", query=query)
        return None


async def tool_web_search(args: dict, ctx: ToolContext) -> str:
    """Search the web — Brave API when configured, else DuckDuckGo HTML."""
    query = args.get("query", "")
    if not query:
        return "Error: query is required"

    brave = await _brave_search(query, ctx)
    if brave:
        return brave
    if brave == "":  # Brave answered fine and genuinely found nothing
        return f"No results found for '{query}'."

    try:
        resp = await ctx.http_client.post(
            DUCKDUCKGO_HTML_URL,
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if resp.status_code != 200:
            # Anti-bot block / rate limit / outage — say so honestly.
            log.warning("web_search.ddg_http", status=resp.status_code, query=query)
            return SEARCH_UNAVAILABLE
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
            # Zero regex matches usually means DDG served an anti-bot/interstitial
            # page (shape change or block), not an empty result set. A real empty
            # SERP still contains the results container; a challenge page doesn't.
            if "result" not in html:
                log.warning("web_search.ddg_blocked", query=query)
                return SEARCH_UNAVAILABLE
            return f"No results found for '{query}'."

        return "\n\n".join(results)

    except Exception as exc:
        log.exception("web_search.error", query=query)
        return f"{SEARCH_UNAVAILABLE} (error: {exc})"


async def tool_web_fetch(args: dict, ctx: ToolContext) -> str:
    """Fetch and extract text content from a URL."""
    url = args.get("url", "")
    if not url:
        return "Error: url is required"

    # Reddit blocks simple HTTP fetches; use old.reddit.com which serves static HTML
    if "reddit.com/" in url and "old.reddit.com" not in url:
        url = url.replace("www.reddit.com", "old.reddit.com").replace("://reddit.com", "://old.reddit.com")

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
