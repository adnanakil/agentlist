"""get_weather tool — current conditions + short forecast via Open-Meteo (no API key).

On-demand: the agent should only call this when the task is actually weather-relevant
(planning an outing, what to wear, stroller walk, etc.) — not on every turn.
"""

from __future__ import annotations

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

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


async def tool_weather(args: dict, ctx: ToolContext) -> str:
    location = (args.get("location") or "New York, NY").strip()
    try:
        days = max(1, min(7, int(args.get("days", 3))))
    except (TypeError, ValueError):
        days = 3

    try:
        geo = await ctx.http_client.get(
            GEOCODE_URL, params={"name": location, "count": 1}, timeout=15
        )
        results = geo.json().get("results") or []
        if not results:
            return f"Couldn't find a location matching '{location}'."
        g = results[0]
        lat, lon = g["latitude"], g["longitude"]
        place = ", ".join(
            x for x in (g.get("name"), g.get("admin1")) if x
        )

        fc = await ctx.http_client.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "America/New_York",
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
                f"{daily['precipitation_probability_max'][i]}% chance precip."
            )
        return "\n".join(lines)
    except Exception as exc:
        log.exception("weather.error", location=location)
        return f"Weather lookup failed: {exc}"
