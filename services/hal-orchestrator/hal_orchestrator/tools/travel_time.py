"""travel_time tool — point-to-point travel time via Google Routes API v2.

Drive mode is traffic-aware (live `duration` vs typical `staticDuration`), so
the agent can say "leave 15 min early". Transit returns real line/departure
info. Requires GOOGLE_MAPS_API_KEY with the Routes API enabled.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

MODES = {
    "drive": "DRIVE",
    "walk": "WALK",
    "bicycle": "TWO_WHEELER",
    "bike": "BICYCLE",
    "transit": "TRANSIT",
}

FIELD_MASK = ",".join(
    [
        "routes.duration",
        "routes.staticDuration",
        "routes.distanceMeters",
        "routes.description",
        "routes.legs.steps.transitDetails.transitLine.nameShort",
        "routes.legs.steps.transitDetails.transitLine.name",
        "routes.legs.steps.transitDetails.stopDetails.departureStop.name",
        "routes.legs.steps.transitDetails.stopDetails.departureTime",
        "routes.legs.steps.transitDetails.stopDetails.arrivalStop.name",
        "routes.legs.steps.transitDetails.stopDetails.arrivalTime",
    ]
)


def _seconds(v) -> int | None:
    """Routes durations come as '6720s' strings."""
    try:
        return int(str(v).rstrip("s"))
    except (TypeError, ValueError):
        return None


def _fmt_duration(seconds: int) -> str:
    m = round(seconds / 60)
    if m < 60:
        return f"{m} min"
    return f"{m // 60} hr {m % 60} min" if m % 60 else f"{m // 60} hr"


def _fmt_local_time(iso: str) -> str:
    from hal_orchestrator.prompts.system import USER_TZ

    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(USER_TZ).strftime("%-I:%M %p")
    except (TypeError, ValueError):
        return iso or "?"


def format_route(route: dict, mode: str, origin: str, destination: str) -> str:
    dur = _seconds(route.get("duration"))
    static = _seconds(route.get("staticDuration"))
    if dur is None:
        return f"No route found from {origin} to {destination} ({mode})."
    miles = round((route.get("distanceMeters") or 0) / 1609.34, 1)
    head = f"{mode.capitalize()} {origin} → {destination}: {_fmt_duration(dur)}"
    if mode == "drive" and static and abs(dur - static) >= 300:
        delta = dur - static
        sign = "slower" if delta > 0 else "faster"
        head += f" with current traffic ({_fmt_duration(static)} typical — {_fmt_duration(abs(delta))} {sign} right now)"
    elif mode == "drive":
        head += " (normal traffic)"
    if miles:
        head += f", {miles} mi"
    lines = [head + "."]
    if mode == "transit":
        for leg in route.get("legs") or []:
            for step in leg.get("steps") or []:
                td = step.get("transitDetails")
                if not td:
                    continue
                line = td.get("transitLine") or {}
                stops = td.get("stopDetails") or {}
                name = line.get("nameShort") or line.get("name") or "transit"
                lines.append(
                    f"  {name}: {(stops.get('departureStop') or {}).get('name', '?')} "
                    f"{_fmt_local_time(stops.get('departureTime'))} → "
                    f"{(stops.get('arrivalStop') or {}).get('name', '?')} "
                    f"{_fmt_local_time(stops.get('arrivalTime'))}"
                )
    return "\n".join(lines)


async def tool_travel_time(args: dict, ctx: ToolContext) -> str:
    key = ctx.settings.google_maps_api_key
    if not key:
        return "Travel time unavailable: GOOGLE_MAPS_API_KEY not configured."

    origin = (args.get("origin") or "").strip()
    destination = (args.get("destination") or "").strip()
    if not origin or not destination:
        return "Error: origin and destination are required."
    mode = (args.get("mode") or "drive").strip().lower()
    travel_mode = MODES.get(mode)
    if not travel_mode:
        return f"Error: mode must be one of {', '.join(sorted(set(MODES)))}."

    body: dict = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": travel_mode,
    }
    if travel_mode == "DRIVE":
        body["routingPreference"] = "TRAFFIC_AWARE"
    # Optional timing: departure_time for drive/transit, arrival_time for
    # transit ("what train gets me there by 7?"). Must be in the future.
    for arg_key, api_key_name in (("departure_time", "departureTime"), ("arrival_time", "arrivalTime")):
        iso = (args.get(arg_key) or "").strip()
        if not iso:
            continue
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            return f"Error: invalid {arg_key} {iso!r}. Use ISO, e.g. 2026-06-12T18:00:00-04:00."
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt > datetime.now(timezone.utc) + timedelta(minutes=1):
            body[api_key_name] = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if "arrivalTime" in body and travel_mode != "TRANSIT":
        return "Error: arrival_time is only supported for transit."
    if "arrivalTime" in body:
        body.pop("departureTime", None)  # Routes API rejects both together

    try:
        resp = await ctx.http_client.post(
            ROUTES_URL,
            json=body,
            headers={
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            timeout=20,
        )
        data = resp.json()
        if resp.status_code != 200:
            err = (data.get("error") or {}).get("message", resp.text[:200])
            log.warning("travel_time.api_error", status=resp.status_code, error=err)
            return f"Travel time lookup failed: {err}"
        routes = data.get("routes") or []
        if not routes:
            return f"No {mode} route found from {origin} to {destination}."
        return format_route(routes[0], mode, origin, destination)
    except Exception as exc:
        log.exception("travel_time.error", origin=origin, destination=destination)
        return f"Travel time lookup failed: {exc}"
