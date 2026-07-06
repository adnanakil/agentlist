"""places tool — nearby place discovery via Google Places API (New).

Text search ("coffee near Fort Greene", "ramen open now") returns real,
current results: name, rating + review count, price level, live open/closed
status, address, phone, and a Google Maps link. With photos=N it also fetches
real photos of the top results and attaches them to the reply (result_images
→ the bridge sends them as iMessage image attachments). Use this for "near
me / open now / find a spot" questions instead of web_search. Requires
GOOGLE_MAPS_API_KEY with the Places API (New) enabled.
"""

from __future__ import annotations

import base64

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PHOTO_URL = "https://places.googleapis.com/v1/{name}/media"
PHOTO_MAX_WIDTH = 800
MAX_PHOTOS = 3

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
        "places.photos.name",
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


async def _attach_photo(ctx: ToolContext, place: dict, key: str) -> bool:
    """Fetch one real photo of `place` and attach it to the reply (bridge
    sends result_images as iMessage attachments). Best-effort: any failure
    just means no photo. Returns True when attached."""
    photos = place.get("photos") or []
    photo_name = (photos[0] or {}).get("name") if photos else None
    if not photo_name or len(ctx.result_images) >= MAX_PHOTOS:
        return False
    try:
        resp = await ctx.http_client.get(
            PHOTO_URL.format(name=photo_name),
            params={"maxWidthPx": PHOTO_MAX_WIDTH, "key": key},
            follow_redirects=True,
            timeout=15,
        )
        if resp.status_code != 200 or not resp.content:
            log.warning("places.photo_failed", status=resp.status_code)
            return False
        mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
        if not mime.startswith("image/"):
            return False
        ext = "png" if "png" in mime else "jpg"
        ctx.result_images.append(
            {
                "mime_type": mime,
                "data": base64.b64encode(resp.content).decode(),
                "ext": ext,
            }
        )
        return True
    except Exception:
        log.exception("places.photo_error")
        return False


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

    try:
        photos = int(args.get("photos") or 0)
    except (TypeError, ValueError):
        photos = 0
    photos = max(0, min(photos, MAX_PHOTOS))

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
        result = format_places(places[:max_results], query)
        if photos and places:
            attached: list[str] = []
            for place in places[:photos]:
                if await _attach_photo(ctx, place, key):
                    attached.append(
                        (place.get("displayName") or {}).get("text") or "?"
                    )
            if attached:
                result += (
                    f"\n\n[📷 attached real photo(s) of: {', '.join(attached)} — "
                    "they'll be sent with your reply automatically; mention "
                    "them naturally, don't describe them]"
                )
        return result
    except Exception as exc:
        log.exception("places.error", query=query)
        return f"Places search failed: {exc}"
