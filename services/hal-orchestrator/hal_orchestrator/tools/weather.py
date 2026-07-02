"""get_weather tool — current conditions + short forecast via Open-Meteo (no API key).

On-demand: the agent should only call this when the task is actually weather-relevant
(planning an outing, what to wear, stroller walk, etc.) — not on every turn.
"""

from __future__ import annotations

import structlog

from hal_orchestrator.prompts.system import resolve_tz
from hal_orchestrator.services.profiles import get_profile
from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Nominatim asks for an identifying UA; volume here is a handful of calls/day.
_NOMINATIM_UA = "HAL-assistant/1.0 (weather geocoding)"


async def _geocode(ctx: ToolContext, location: str) -> tuple[float, float, str] | None:
    """(lat, lon, label) for a location string, or None.

    Nominatim first: it handles the compound strings real profiles hold
    ("Chelsea, Manhattan, New York, NY", "Fort Greene, Brooklyn"), which
    Open-Meteo's geocoder returns NOTHING for — even plain "New York, NY"
    fails there, and bare "Chelsea" resolves to Chelsea, Vermont. Open-Meteo
    stays as the fallback if Nominatim is down."""
    try:
        r = await ctx.http_client.get(
            NOMINATIM_URL,
            params={"q": location, "format": "json", "limit": 1},
            headers={"User-Agent": _NOMINATIM_UA},
            timeout=15,
        )
        if r.status_code == 200:
            hits = r.json() or []
            if hits:
                h = hits[0]
                label = ", ".join((h.get("display_name") or location).split(", ")[:2])
                return float(h["lat"]), float(h["lon"]), label
    except Exception:
        log.exception("weather.nominatim_failed", location=location)

    try:
        geo = await ctx.http_client.get(
            GEOCODE_URL, params={"name": location, "count": 1}, timeout=15
        )
        results = geo.json().get("results") or []
        if results:
            g = results[0]
            label = ", ".join(x for x in (g.get("name"), g.get("admin1")) if x)
            return g["latitude"], g["longitude"], label
    except Exception:
        log.exception("weather.geocode_fallback_failed", location=location)
    return None

# WMO weather codes -> human text
_WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "rain showers", 82: "heavy rain showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms w/ hail", 99: "severe thunderstorms",
}


def _code(c) -> str:
    try:
        return _WMO.get(int(c), "unknown")
    except (TypeError, ValueError):
        return "unknown"


# An hour counts as "wet" at/above this precip probability (or real accumulation).
_WET_PROB = 40
_WET_MM = 0.2
_RAIN_HORIZON_HOURS = 48


def _fmt_hour(iso: str) -> str:
    """'2026-06-15T14:00' -> 'Tue 2pm' (local; the API is queried in ET)."""
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    h = dt.hour
    ampm = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{dt.strftime('%a')} {h12}{ampm}"


def _rain_windows(hourly: dict) -> str | None:
    """Compact summary of WHEN it rains over the next ~48h: contiguous wet-hour
    windows with peak probability. Returns None if hourly data is unavailable,
    a 'dry' line if there are no wet hours, else the windows."""
    times = hourly.get("time") or []
    probs = hourly.get("precipitation_probability") or []
    amts = hourly.get("precipitation") or []
    if not times or not probs:
        return None

    n = min(len(times), len(probs), _RAIN_HORIZON_HOURS)
    windows: list[tuple[int, int, int]] = []  # (start_idx, end_idx, peak_prob)
    i = 0
    while i < n:
        p = probs[i] or 0
        a = amts[i] if i < len(amts) and amts[i] is not None else 0
        if p >= _WET_PROB or a >= _WET_MM:
            j = i
            peak = p
            while j + 1 < n:
                np = probs[j + 1] or 0
                na = amts[j + 1] if (j + 1) < len(amts) and amts[j + 1] is not None else 0
                if np >= _WET_PROB or na >= _WET_MM:
                    peak = max(peak, np)
                    j += 1
                else:
                    break
            windows.append((i, j, peak))
            i = j + 1
        else:
            i += 1

    if not windows:
        return f"no significant rain in the next {n}h — dry through your plan."

    parts = []
    for start, end, peak in windows[:5]:
        # end is the last wet hour; the band runs to the start of the next hour.
        end_iso = times[end + 1] if end + 1 < len(times) else times[end]
        parts.append(f"{_fmt_hour(times[start])}–{_fmt_hour(end_iso)} (~{peak}%)")
    return "; ".join(parts) + " — otherwise dry."


async def tool_weather(args: dict, ctx: ToolContext) -> str:
    location = (args.get("location") or "New York, NY").strip()
    try:
        days = max(1, min(7, int(args.get("days", 3))))
    except (TypeError, ValueError):
        days = 3

    # Align the hourly/daily forecast buckets to the user's local time (1:1 only;
    # a group has no single user, so fall back to the default tz).
    profile = await get_profile(ctx.session, ctx.phone) if not ctx.is_group else None
    tz = resolve_tz(profile)

    try:
        hit = await _geocode(ctx, location)
        if hit is None:
            return (
                f"Couldn't find a location matching '{location}'. Try a simpler "
                "form like 'Brooklyn NY' or a city name."
            )
        lat, lon, place = hit

        fc = await ctx.http_client.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "hourly": "precipitation_probability,precipitation",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": tz.key,
                "forecast_days": days,
            },
            timeout=15,
        )
        data = fc.json()
        cur = data.get("current", {})
        daily = data.get("daily", {})

        lines = [
            f"Weather for {place}:",
            f"Now: {round(cur.get('temperature_2m', 0))}°F "
            f"(feels {round(cur.get('apparent_temperature', 0))}°F), "
            f"{_code(cur.get('weather_code'))}, wind {round(cur.get('wind_speed_10m', 0))} mph.",
        ]
        dates = daily.get("time", [])
        for i, d in enumerate(dates):
            label = "Today" if i == 0 else "Tomorrow" if i == 1 else d
            lines.append(
                f"{label}: {_code(daily['weather_code'][i])}, "
                f"{round(daily['temperature_2m_min'][i])}–{round(daily['temperature_2m_max'][i])}°F, "
                f"{daily['precipitation_probability_max'][i]}% chance precip (daily max)."
            )

        # WHEN it rains — the daily % above is a whole-day max and is often
        # driven by an overnight band that doesn't touch a daytime plan. The
        # hourly windows below are what to reason from for a specific outing.
        rain = _rain_windows(data.get("hourly", {}))
        if rain is not None:
            lines.append("")
            lines.append(
                "Rain timing (reason from THESE for a plan, not the daily %): "
                + rain
            )
        return "\n".join(lines)
    except Exception as exc:
        log.exception("weather.error", location=location)
        return f"Weather lookup failed: {exc}"
