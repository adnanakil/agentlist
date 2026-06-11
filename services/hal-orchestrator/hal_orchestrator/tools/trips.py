"""Trip coordination tool — plan group trips via iMessage."""

from __future__ import annotations

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()


async def tool_trip(args: dict, ctx: ToolContext) -> str:
    """Handle trip coordination actions."""
    from hal_orchestrator.services.date_parser import parse_dates
    from hal_orchestrator.services.trips import (
        add_availability,
        add_options,
        cancel_trip,
        cast_vote,
        compute_overlap,
        create_trip,
        get_active_trip,
        get_trip_status,
        lock_dates,
        tally_votes,
    )

    action = args.get("action", "")
    # Always use ctx.chat_id from the bridge — Gemini doesn't know the real chat_id
    default_chat_id = ctx.chat_id or ctx.phone

    # Always use the bridge-provided chat_id, not what Gemini guesses
    chat_id = default_chat_id

    # The person speaking — in groups ctx.phone is the group silo, so fall
    # back through sender_phone for per-person attribution (votes, created_by).
    actor = ctx.sender_phone or ctx.phone

    if action == "create":
        location = args.get("location", "")
        if not location:
            return "Error: location is required."
        group_name = args.get("group_name", "")
        result = await create_trip(
            ctx.session,
            chat_id=chat_id,
            location=location,
            created_by=actor,
            group_name=group_name or None,
        )
        return (
            f"Trip to {location} created! Status: collecting availability. "
            f"Ask everyone when they're free."
        )

    elif action == "status":

        return await get_trip_status(ctx.session, chat_id)

    elif action == "add_availability":

        phone = args.get("phone", actor)
        name = args.get("name", phone)
        available = args.get("available", [])
        unavailable = args.get("unavailable", [])
        return await add_availability(
            ctx.session, chat_id, phone, name, available, unavailable
        )

    elif action == "parse_and_add":

        phone = args.get("phone", actor)
        name = args.get("name", phone)
        text = args.get("text", "")
        if not text:
            return "Error: text is required for parsing."

        trip = await get_active_trip(ctx.session, chat_id)
        if not trip:
            return "No active trip in this chat."

        parsed = await parse_dates(
            ctx.http_client, ctx.settings, text, trip.location
        )

        if parsed.get("none"):
            return "No dates found in that message."

        available = parsed.get("available", [])
        unavailable = parsed.get("unavailable", [])

        if not available and not unavailable:
            return "No dates found in that message."

        result = await add_availability(
            ctx.session, chat_id, phone, name, available, unavailable
        )

        # Also compute current overlap
        trip = await get_active_trip(ctx.session, chat_id)
        if trip and trip.participants:
            overlap = compute_overlap(trip.participants)
            if overlap:
                overlap_strs = [f"{r['start']} to {r['end']}" for r in overlap]
                result += f"\nCurrent overlap: {'; '.join(overlap_strs)}"
            else:
                result += "\nNo overlapping dates yet."

        return result

    elif action == "lock_dates":

        start = args.get("start", "")
        end = args.get("end", "")
        if not start or not end:
            return "Error: start and end dates are required."
        return await lock_dates(ctx.session, chat_id, start, end)

    elif action == "search_airbnb":

        trip = await get_active_trip(ctx.session, chat_id)
        if not trip:
            return "No active trip in this chat."
        if not trip.locked_dates:
            return "Lock dates first before searching."

        location = trip.location
        start = trip.locked_dates["start"]
        end = trip.locked_dates["end"]
        # Use explicit guest count from args, or fall back to participant count
        guests = args.get("guests", 0)
        if isinstance(guests, str):
            try:
                guests = int(guests)
            except ValueError:
                guests = 0
        if not guests:
            guests = max(len(trip.participants), 2)

        # Calculate minimum bedrooms (roughly 2 guests per bedroom)
        min_bedrooms = max((guests + 1) // 2, 1)

        from hal_orchestrator.tools.browser import tool_browser
        from hal_orchestrator.tools.web_search import tool_web_search

        # Build Airbnb search URL for reference
        airbnb_search_url = (
            f"https://www.airbnb.com/s/{location.replace(' ', '-')}/homes"
            f"?checkin={start}&checkout={end}&adults={guests}"
            f"&room_types%5B%5D=Entire%20home"
            f"&min_bedrooms={min_bedrooms}"
        )

        # Strategy: use Google to find Airbnb listings (avoids bot detection),
        # then verify each listing via browser.
        search_query = (
            f"site:airbnb.com/rooms "
            f"{location} entire home "
            f"{min_bedrooms}+ bedrooms {guests} guests"
        )

        search_result = await tool_web_search(
            {"query": search_query}, ctx
        )

        # Also try browser on Airbnb directly (may work sometimes)
        js_extract = """
        (() => {
            const listings = [];
            const cards = document.querySelectorAll('a[href*="/rooms/"]');
            const seen = new Set();
            for (const card of cards) {
                const href = card.getAttribute('href');
                const match = href.match(/\\/rooms\\/(\\d+)/);
                if (!match || seen.has(match[1])) continue;
                seen.add(match[1]);
                let container = card.closest('[data-testid="card-container"]')
                    || card.closest('[itemprop="itemListElement"]')
                    || card.parentElement?.parentElement?.parentElement;
                const text = container ? container.innerText : card.innerText;
                const fullUrl = 'https://www.airbnb.com' + href.split('?')[0];
                listings.push({ url: fullUrl, room_id: match[1], text: text.substring(0, 500) });
                if (listings.length >= 10) break;
            }
            return JSON.stringify(listings);
        })()
        """

        browser_listings = []
        try:
            eval_result = await tool_browser(
                {"url": airbnb_search_url, "action": "evaluate", "javascript": js_extract},
                ctx,
            )
            import json as _json
            raw = eval_result
            if "Result: " in raw:
                raw = raw.split("Result: ", 1)[1]
            browser_listings = _json.loads(raw)
        except Exception:
            pass

        # Combine results
        parts = [
            f"Airbnb search for {location} ({start} to {end}, "
            f"{guests} guests, {min_bedrooms}+ bedrooms, entire homes only):\n",
            f"Direct Airbnb link: {airbnb_search_url}\n",
        ]

        if browser_listings:
            parts.append("== Listings from Airbnb ==")
            for i, l in enumerate(browser_listings, 1):
                parts.append(f"{i}. URL: {l['url']}")
                parts.append(f"   Details: {l['text']}\n")

        if search_result:
            parts.append("\n== Google search results ==")
            parts.append(search_result)

        parts.append(
            f"\nPick the 3 best ENTIRE HOME options that fit {guests} people "
            f"with at least {min_bedrooms} bedrooms. "
            f"Use trip(action='save_options', options=[...]) to save them. "
            f"Each option MUST have a real airbnb.com/rooms/XXXXX URL. "
            f"Do NOT invent or guess URLs — only use URLs from the results above."
        )

        return "\n".join(parts)

    elif action == "save_options":
        # Called by Gemini after it parses browser results

        options = args.get("options", [])
        if not options:
            return "Error: options list is required."
        result = await add_options(ctx.session, chat_id, options)
        lines = [result]
        for i, opt in enumerate(options, 1):
            lines.append(
                f"{i}. {opt.get('title', 'Listing')} — "
                f"${opt.get('price_per_night', '?')}/night — "
                f"{opt.get('url', '')}"
            )
        return "\n".join(lines)

    elif action == "vote":

        phone = args.get("phone", actor)
        option = args.get("option", 0)
        if isinstance(option, str):
            try:
                option = int(option)
            except ValueError:
                return "Error: option must be a number."
        return await cast_vote(ctx.session, chat_id, phone, option)

    elif action == "tally":

        return await tally_votes(ctx.session, chat_id)

    elif action == "cancel":

        return await cancel_trip(ctx.session, chat_id)

    else:
        return (
            "Unknown action. Available: create, status, parse_and_add, "
            "add_availability, lock_dates, search_airbnb, save_options, "
            "vote, tally, cancel"
        )


def _days_between(start: str, end: str) -> int:
    """Calculate days between two ISO date strings."""
    from datetime import date as dt_date

    try:
        s = dt_date.fromisoformat(start)
        e = dt_date.fromisoformat(end)
        return max((e - s).days, 1)
    except ValueError:
        return 3
