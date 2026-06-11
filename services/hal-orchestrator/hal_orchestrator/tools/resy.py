"""resy tool — find restaurant tables and hand the user a Resy link to book.

Read-only: HAL searches and checks availability, then gives a Resy deep link so
the user books on THEIR OWN account. No booking on anyone's behalf, no stored
credentials. Public info — allowed everywhere, including groups.
"""

from __future__ import annotations

import structlog

from hal_orchestrator.services import resy as r
from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()


def _err(kind: str) -> str:
    if kind == "rate_limited":
        return "Resy is rate-limiting us right now — try again in a bit."
    return "Resy had an error — try again shortly."


async def tool_resy(args: dict, ctx: ToolContext) -> str:
    if not r.is_configured(ctx.settings):
        return "Resy isn't set up on this HAL instance yet."
    action = args.get("action", "")

    if action == "search":
        query = args.get("query", "")
        if not query:
            return "Error: query (a restaurant name) is required."
        try:
            hits = await r.search_venues(ctx.http_client, ctx.settings, query)
        except r.ResyError as e:
            return _err(e.kind)
        if not hits:
            return f"No Resy venues found for '{query}'."
        lines = []
        for h in hits[:6]:
            if not h.get("venue_id"):
                continue
            lines.append(
                f"- {h['name']} ({h.get('location') or '?'}) "
                f"[venue_id: {h['venue_id']}] {r.build_booking_url(h)}"
            )
        return "Found on Resy:\n" + "\n".join(lines)

    if action == "availability":
        venue_id = args.get("venue_id")
        date = args.get("date")
        party_size = int(args.get("party_size", 2) or 2)
        venue = None
        if args.get("query"):
            try:
                hits = await r.search_venues(ctx.http_client, ctx.settings, args["query"])
            except r.ResyError as e:
                return _err(e.kind)
            if not hits:
                return f"No venue found for '{args['query']}'."
            venue = hits[0]
            venue_id = venue["venue_id"]
        if not venue_id or not date:
            return "Error: need a venue (venue_id or query) and a date (YYYY-MM-DD)."
        try:
            slots = await r.get_availability(
                ctx.http_client, ctx.settings, str(venue_id), date, party_size
            )
        except r.ResyError as e:
            return _err(e.kind)
        # Build the booking link (use the resolved venue, else a minimal stub).
        link = (
            r.build_booking_url(venue, date, party_size)
            if venue
            else f"https://resy.com/cities/new-york-ny/venues/?date={date}&seats={party_size}"
        )
        if not slots:
            return (
                f"No open tables for {party_size} on {date}. "
                f"Check the calendar / other dates here: {link}"
            )
        times = ", ".join(
            f"{(s['time'] or '').split(' ')[-1][:5]}{' ' + s['type'] if s.get('type') else ''}"
            for s in slots if s.get("time")
        )
        return (
            f"Open for {party_size} on {date}: {times}.\n"
            f"Book any of these on Resy here: {link}"
        )

    return f"Unknown resy action: {action}. Use: search, availability."
