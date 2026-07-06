"""nyc_events tool — query the Ephemera NYC events engine.

Ephemera (a sibling service) scrapes ~330 NYC venue/aggregator sites daily,
extracts structured events with a model, geocodes them, and serves them from
one API. This tool is HAL's read path: real, current, curated NYC events for
"what's going on this weekend / things to do near X" — strictly better than
web_search for NYC event discovery because every result is fresh, structured,
and carries a link.

API contract (GET {EPHEMERA_URL}/api/events):
  since/until (YYYY-MM-DD) · near ("lat,lng") + radius_km · category · q ·
  limit → {success, count, events: [{title, description, time, date,
  location, category, borough, neighborhood, lat, lng, link, ticketLink}],
  lastFetched}
"""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

DEFAULT_DAYS_AHEAD = 7
MAX_DAYS_AHEAD = 30
DEFAULT_LIMIT = 12
MAX_LIMIT = 25


def format_event(e: dict) -> str:
    """One event as an iMessage-friendly block. Pure so it's unit-testable."""
    when = (e.get("time") or "").strip()
    date = (e.get("date") or "").strip()
    if date and date not in when:
        try:
            when = f"{datetime.fromisoformat(date):%a %b %-d}" + (
                f", {when}" if when else ""
            )
        except ValueError:
            when = f"{date}{', ' + when if when else ''}"
    head = f"- {when or 'Date TBA'}: {e.get('title') or 'Untitled'}"
    where_bits = [b for b in (e.get("location"), e.get("neighborhood")) if b]
    lines = [head]
    if where_bits:
        lines.append(f"  {' — '.join(dict.fromkeys(where_bits))}")
    link = e.get("ticketLink") or e.get("link")
    if link:
        lines.append(f"  {link}")
    return "\n".join(lines)


def format_events(payload: dict, limit: int) -> str:
    events = (payload.get("events") or [])[:limit]
    if not events:
        return (
            "No matching NYC events found for that filter. Try widening the "
            "dates or dropping the category/keyword."
        )
    out = "\n".join(format_event(e) for e in events)
    fetched = (payload.get("lastFetched") or "")[:10]
    if fetched:
        out += f"\n(source: Ephemera, scraped {fetched})"
    return out


async def tool_nyc_events(args: dict, ctx: ToolContext) -> str:
    base = (ctx.settings.ephemera_url or "").rstrip("/")
    if not base:
        return "NYC events unavailable: EPHEMERA_URL not configured."

    try:
        days = int(args.get("days_ahead") or DEFAULT_DAYS_AHEAD)
    except (TypeError, ValueError):
        days = DEFAULT_DAYS_AHEAD
    days = max(1, min(days, MAX_DAYS_AHEAD))
    try:
        limit = int(args.get("limit") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))

    from hal_orchestrator.prompts.system import USER_TZ

    today = datetime.now(USER_TZ).date()
    params: dict = {
        "since": (args.get("since") or today.isoformat()),
        "until": (args.get("until") or (today + timedelta(days=days)).isoformat()),
        "limit": limit,
    }
    for key in ("category", "q", "near", "radius_km"):
        if args.get(key):
            params[key] = args[key]

    try:
        resp = await ctx.http_client.get(
            f"{base}/api/events", params=params, timeout=15
        )
        if resp.status_code != 200:
            log.warning("nyc_events.http_error", status=resp.status_code)
            return f"NYC events lookup failed (HTTP {resp.status_code})."
        payload = resp.json()
    except Exception as exc:
        log.exception("nyc_events.error")
        return f"NYC events lookup failed: {exc}"

    if not payload.get("success", True):
        return "NYC events lookup failed (engine returned an error)."
    return format_events(payload, limit)
