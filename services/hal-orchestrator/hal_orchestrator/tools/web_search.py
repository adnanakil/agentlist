"""web_search and web_fetch tools — Brave API (when keyed) with DuckDuckGo
HTML-scrape fallback, + page fetching.

The failure-honesty rule: a blocked/erroring search must NEVER read as "no
results" — the model would then confidently tell the user nothing exists.
Unavailability is reported as its own distinct message so the model retries
or switches to browser/web_fetch instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

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


@dataclass
class WebSearchResults:
    """Structured search output shared by the rendered tool and by callers
    (grocery ASIN discovery) that need URLs, not prose.

    `available=False` means the search service errored or blocked the request —
    NOT an empty result set. That distinction is the whole failure-honesty rule:
    an empty `results` with `available=True` genuinely found nothing.
    """

    results: list[dict] = field(default_factory=list)  # [{title, url, snippet}]
    available: bool = True


def _unwrap_ddg_url(href: str) -> str:
    """DuckDuckGo HTML wraps every result link in a /l/?uddg=<real-url> redirect;
    unwrap it so callers get the real target URL (needed to read Amazon ASINs)."""
    if "uddg=" not in href:
        return href
    query = urlparse(href if "://" in href else "https:" + href).query
    target = parse_qs(query).get("uddg")
    return target[0] if target else href


async def _brave_results(query: str, ctx: ToolContext, count: int) -> list[dict] | None:
    """Brave Search API — reliable JSON. Returns a (possibly empty) result list,
    or None to signal 'no key / errored, fall back to DDG'."""
    key = getattr(ctx.settings, "brave_search_api_key", "")
    if not key:
        return None
    try:
        resp = await ctx.http_client.get(
            BRAVE_SEARCH_URL,
            params={"q": query, "count": count},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning("web_search.brave_http", status=resp.status_code)
            return None
        items = (resp.json().get("web") or {}).get("results") or []
        out = []
        for it in items[:count]:
            title = (it.get("title") or "").strip()
            url = (it.get("url") or "").strip()
            desc = re.sub(r"<[^>]+>", "", it.get("description") or "").strip()
            if title and url:
                out.append({"title": title, "url": url, "snippet": desc})
        return out
    except Exception:
        log.exception("web_search.brave_error", query=query)
        return None


async def _ddg_results(query: str, ctx: ToolContext, count: int) -> list[dict] | None:
    """DuckDuckGo HTML scrape. Returns a (possibly empty) result list for a real
    SERP, or None when the request was blocked/errored (an anti-bot page)."""
    try:
        resp = await ctx.http_client.post(
            DUCKDUCKGO_HTML_URL,
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
    except Exception:
        log.exception("web_search.error", query=query)
        return None
    if resp.status_code != 200:
        # Anti-bot block / rate limit / outage — signal unavailable, not empty.
        log.warning("web_search.ddg_http", status=resp.status_code, query=query)
        return None
    html = resp.text

    # Pattern: <a class="result__a" href="...">title</a> ... <a class="result__snippet">snippet</a>
    matches = re.findall(
        r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</a>',
        html,
        re.DOTALL,
    )
    out = []
    for url, title, snippet in matches[:count]:
        title = re.sub(r"<[^>]+>", "", title).strip()
        snippet = re.sub(r"<[^>]+>", "", snippet).strip()
        url = _unwrap_ddg_url(url)
        if title and url:
            out.append({"title": title, "url": url, "snippet": snippet})

    if not out and "result" not in html:
        # Zero matches AND no results container: DDG served an anti-bot/
        # interstitial page (shape change or block), not an empty result set.
        log.warning("web_search.ddg_blocked", query=query)
        return None
    return out


async def search_web(query: str, ctx: ToolContext, *, count: int = 5) -> WebSearchResults:
    """Structured web search: Brave when keyed, else DuckDuckGo HTML.

    The single search client. `tool_web_search` renders this for the model;
    grocery ASIN discovery consumes the raw URLs. A blocked/errored search
    returns `available=False` so callers never mistake it for 'nothing exists'.
    """
    brave = await _brave_results(query, ctx, count)
    if brave is not None:
        return WebSearchResults(results=brave, available=True)
    ddg = await _ddg_results(query, ctx, count)
    if ddg is None:
        return WebSearchResults(results=[], available=False)
    return WebSearchResults(results=ddg, available=True)


async def tool_web_search(args: dict, ctx: ToolContext) -> str:
    """Search the web — Brave API when configured, else DuckDuckGo HTML."""
    query = args.get("query", "")
    if not query:
        return "Error: query is required"

    res = await search_web(query, ctx)
    if not res.available:
        return SEARCH_UNAVAILABLE
    if not res.results:
        return f"No results found for '{query}'."
    return "\n\n".join(
        f"{r['title']}\n{r['snippet']}\n{r['url']}" for r in res.results
    )


async def tool_web_fetch(args: dict, ctx: ToolContext) -> str:
    """Fetch and extract text content from a URL."""
    url = args.get("url", "")
    if not url:
        return "Error: url is required"

    # Reddit blocks simple HTTP fetches; use old.reddit.com which serves static HTML
    if "reddit.com/" in url and "old.reddit.com" not in url:
        url = url.replace("www.reddit.com", "old.reddit.com").replace("://reddit.com", "://old.reddit.com")

    # SSRF guard: refuse fetches to internal/private hosts (cloud metadata,
    # *.railway.internal, localhost). The model picks this URL from user text.
    from hal_orchestrator.services.url_guard import check_url

    reason = await check_url(
        url, allow_private=ctx.settings.allow_private_network_fetch
    )
    if reason:
        log.warning("web_fetch.blocked", url=url[:120], reason=reason)
        return f"Can't fetch that URL ({reason})."

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
