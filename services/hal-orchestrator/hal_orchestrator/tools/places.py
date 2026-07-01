"""places tool — nearby place discovery via Google Places API (New).

Text search ("coffee near Fort Greene", "ramen open now") returns real,
current results: name, rating + review count, price level, live open/closed
status, address, phone, and a Google Maps link. Use this for "near me / open
now / find a spot" questions instead of web_search. Requires
GOOGLE_MAPS_API_KEY with the Places API (New) enabled.
"""

from __future__ import annotations

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = ",".join(
    [
        "places.displayName",
        "places.formattedAddress",
        "places.rating",
        "places.userRatingCount",
        "places.priceLevel",
        "places.currentOpeningHours.openNow",
        "places.nationalPhoneNumber",
        "places.googleMapsUri",
        "places.websiteUri",
    ]
)

# Places API (New) returns priceLevel as an enum string.
PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": "Free",
    "PRICE_LEVEL_INEXPENSIVE": "$",
    "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$",
    "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
}


def _price(level) -> str | None:
    return PRICE_LEVELS.get(level)


def format_place(place: dict, index: int) -> str:
    name = (place.get("displayName") or {}).get("text") or "Unknown"
    bits = []
    rating = place.get("rating")
    if rating is not None:
        count = place.get("userRatingCount")
        bits.append(f"{rating}★ ({count:,})" if count else f"{rating}★")
    price = _price(place.get("priceLevel"))
    if price:
        bits.append(price)
    open_now = (place.get("currentOpeningHours") or {}).get("openNow")
    if open_now is True:
        bits.append("open now")
    elif open_now is False:
        bits.append("closed")

    head = f"{index}. {name}"
    if bits:
        head += " — " + " · ".join(bits)
    lines = [head]

    addr = place.get("formattedAddress")
    if addr:
        lines.append(f"   {addr}")
    phone = place.get("nationalPhoneNumber")
    if phone:
        lines.append(f"   {phone}")
    maps_uri = place.get("googleMapsUri")
    if maps_uri:
        lines.append(f"   {maps_uri}")
    return "\n".join(lines)


def format_places(places: list[dict], query: str) -> str:
    if not places:
        return f"No places found for {query!r}."
    return "\n".join(format_place(p, i) for i, p in enumerate(places, 1))


async def tool_places(args: dict, ctx: ToolContext) -> str:
    key = ctx.settings.google_maps_api_key
    if not key:
        return "Places search unavailable: GOOGLE_MAPS_API_KEY not configured."

    query = (args.get("query") or "").strip()
    if not query:
        return "Error: query is required (e.g. 'coffee shops near Fort Greene Brooklyn')."

    try:
        max_results = int(args.get("max_results") or 5)
    except (TypeError, ValueError):
        max_results = 5
    max_results = max(1, min(max_results, 8))

    body: dict = {"textQuery": query, "maxResultCount": max_results}
    if args.get("open_now"):
        body["openNow"] = True

    try:
        resp = await ctx.http_client.post(
            SEARCH_URL,
            json=body,
            headers={
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            timeout=10,
        )
        data = resp.json()
        if resp.status_code != 200:
            err = data.get("error") or {}
            msg = err.get("message") or resp.text[:200]
            if resp.status_code == 403 or err.get("status") == "PERMISSION_DENIED":
                log.warning("places.permission_denied", error=msg)
                return (
                    "Places search failed (permission denied): the Places API (New) "
                    f"may not be enabled for this key. {msg}"
                )
            log.warning("places.api_error", status=resp.status_code, error=msg)
            return f"Places search failed (HTTP {resp.status_code}): {msg}"
        places = data.get("places") or []
        return format_places(places[:max_results], query)
    except Exception as exc:
        log.exception("places.error", query=query)
        return f"Places search failed: {exc}"
