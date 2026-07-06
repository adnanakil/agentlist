"""get_weather tool — current conditions + short forecast, no-key providers only.

On-demand: the agent should only call this when the task is actually weather-relevant
(planning an outing, what to wear, stroller walk, etc.) — not on every turn.

Reliability: geocoding already has its own ladder (Nominatim → Open-Meteo), but
the FORECAST fetch was a single Open-Meteo call — that layer was hard-down
Jul 1–3 and the tool returned error strings for days. Forecasts now fail over
to MET Norway (api.met.no, no key, UA header required), and a 30-min
last-known-good cache per location covers the everything-down case, labeled
stale ("as of HH:MM") so the model never presents old data as live.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import structlog

from hal_orchestrator.prompts.system import resolve_tz
from hal_orchestrator.services.profiles import get_profile
from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MET_NO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"

# Nominatim asks for an identifying UA; volume here is a handful of calls/day.
_NOMINATIM_UA = "HAL-assistant/1.0 (weather geocoding)"
# api.met.no rejects anonymous clients (403 without a UA); same volume story.
_MET_NO_UA = "HAL-assistant/1.0 (weather failover)"


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


# met.no symbol_code base (suffixes: _day/_night/_polartwilight) -> human text,
# aligned with the _WMO vocabulary so both providers read the same.
_MET_SYMBOL = {
    "clearsky": "clear", "fair": "mostly clear", "partlycloudy": "partly cloudy",
    "cloudy": "overcast", "fog": "foggy",
    "lightrain": "light rain", "rain": "rain", "heavyrain": "heavy rain",
    "lightrainshowers": "rain showers", "rainshowers": "rain showers",
    "heavyrainshowers": "heavy rain showers",
    "lightsleet": "sleet", "sleet": "sleet", "heavysleet": "heavy sleet",
    "lightsleetshowers": "sleet showers", "sleetshowers": "sleet showers",
    "heavysleetshowers": "heavy sleet showers",
    "lightsnow": "light snow", "snow": "snow", "heavysnow": "heavy snow",
    "lightsnowshowers": "snow showers", "snowshowers": "snow showers",
    "heavysnowshowers": "heavy snow showers",
    "rainandthunder": "thunderstorms", "heavyrainandthunder": "thunderstorms",
    "lightrainandthunder": "thunderstorms",
    "rainshowersandthunder": "thunderstorms",
    "heavyrainshowersandthunder": "thunderstorms",
    "lightssleetshowersandthunder": "thunderstorms",
    "sleetandthunder": "thunderstorms", "snowandthunder": "thunderstorms",
}


def _met_symbol(code) -> str:
    base = str(code or "").split("_")[0]
    return _MET_SYMBOL.get(base, base or "unknown")


def _c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def _ms_to_mph(ms: float) -> float:
    return ms * 2.23694


# An hour counts as "wet" at/above this precip probability (or real accumulation).
_WET_PROB = 40
_WET_MM = 0.2
_RAIN_HORIZON_HOURS = 48


def _fmt_hour(iso: str) -> str:
    """'2026-06-15T14:00' -> 'Tue 2pm' (local; the API is queried in ET)."""
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
    a 'dry' line if there are no wet hours, else the windows.

    Providers without hourly probabilities (met.no compact) pass all-None
    probs: wetness is then decided by accumulation alone and windows are
    labeled with peak mm/h instead of a %."""
    times = hourly.get("time") or []
    probs = hourly.get("precipitation_probability") or []
    amts = hourly.get("precipitation") or []
    if not times or not probs:
        return None

    n = min(len(times), len(probs), _RAIN_HORIZON_HOURS)
    has_probs = any(p is not None for p in probs[:n])
    windows: list[tuple[int, int, int, float]] = []  # (start, end, peak_prob, peak_mm)
    i = 0
    while i < n:
        p = probs[i] or 0
        a = amts[i] if i < len(amts) and amts[i] is not None else 0
        if p >= _WET_PROB or a >= _WET_MM:
            j = i
            peak = p
            peak_amt = a
            while j + 1 < n:
                np = probs[j + 1] or 0
                na = amts[j + 1] if (j + 1) < len(amts) and amts[j + 1] is not None else 0
                if np >= _WET_PROB or na >= _WET_MM:
                    peak = max(peak, np)
                    peak_amt = max(peak_amt, na)
                    j += 1
                else:
                    break
            windows.append((i, j, peak, peak_amt))
            i = j + 1
        else:
            i += 1

    if not windows:
        return f"no significant rain in the next {n}h — dry through your plan."

    parts = []
    for start, end, peak, peak_amt in windows[:5]:
        # end is the last wet hour; the band runs to the start of the next hour.
        end_iso = times[end + 1] if end + 1 < len(times) else times[end]
        label = f"~{peak}%" if has_probs else f"~{peak_amt:g}mm/h"
        parts.append(f"{_fmt_hour(times[start])}–{_fmt_hour(end_iso)} ({label})")
    return "; ".join(parts) + " — otherwise dry."


# --------------------------------------------------------------------------- #
# Forecast providers — each returns the full formatted reply or raises.
# --------------------------------------------------------------------------- #


def _format_open_meteo(data: dict, place: str) -> str:
    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    # A 200 with a degraded payload must fail over, not render zeros.
    if not cur or not dates:
        raise ValueError("open-meteo returned no forecast payload")

    lines = [
        f"Weather for {place}:",
        f"Now: {round(cur.get('temperature_2m', 0))}°F "
        f"(feels {round(cur.get('apparent_temperature', 0))}°F), "
        f"{_code(cur.get('weather_code'))}, wind {round(cur.get('wind_speed_10m', 0))} mph.",
    ]
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


async def _forecast_open_meteo(
    ctx: ToolContext, lat: float, lon: float, place: str, days: int, tz: ZoneInfo
) -> str:
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
    fc.raise_for_status()
    return _format_open_meteo(fc.json(), place)


def _format_met_no(series: list, place: str, days: int, tz: ZoneInfo) -> str:
    """met.no compact timeseries -> the same reply shape as Open-Meteo. The
    data forces two differences: compact has no feels-like and no precip
    probability, so 'Now' drops feels-like and daily lines report accumulation
    (mm) instead of a chance %. Units arrive as °C / m/s / mm."""

    def _instant(e: dict) -> dict:
        return ((e.get("data") or {}).get("instant") or {}).get("details") or {}

    def _block(e: dict, key: str) -> dict:
        return (e.get("data") or {}).get(key) or {}

    def _symbol(e: dict) -> str | None:
        for key in ("next_1_hours", "next_6_hours", "next_12_hours"):
            code = (_block(e, key).get("summary") or {}).get("symbol_code")
            if code:
                return code
        return None

    parsed: list[tuple[datetime, dict]] = []
    for e in series:
        try:
            dt = datetime.fromisoformat(str(e["time"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        parsed.append((dt.astimezone(tz), e))
    if not parsed:
        raise ValueError("met.no returned no usable timeseries")

    now_d = _instant(parsed[0][1])
    lines = [
        f"Weather for {place}:",
        f"Now: {round(_c_to_f(now_d.get('air_temperature') or 0))}°F, "
        f"{_met_symbol(_symbol(parsed[0][1]))}, "
        f"wind {round(_ms_to_mph(now_d.get('wind_speed') or 0))} mph.",
    ]

    # Daily min/max + accumulation, bucketed on the user's local dates.
    day_order: list = []
    by_day: dict = {}
    for dt, e in parsed:
        d = dt.date()
        if d not in by_day:
            by_day[d] = []
            day_order.append(d)
        by_day[d].append((dt, e))

    for i, d in enumerate(day_order[:days]):
        entries = by_day[d]
        temps = [t for t in (_instant(e).get("air_temperature") for _, e in entries)
                 if t is not None]
        if not temps:
            continue
        # next_1_hours where present, else next_6_hours: met.no's 6-hourly
        # tail spaces entries 6h apart, so the blocks tile without overlap.
        precip = 0.0
        for _, e in entries:
            n1 = _block(e, "next_1_hours").get("details") or {}
            if "precipitation_amount" in n1:
                precip += n1.get("precipitation_amount") or 0
            else:
                precip += (_block(e, "next_6_hours").get("details") or {}).get(
                    "precipitation_amount"
                ) or 0
        midday = min(entries, key=lambda pair: abs(pair[0].hour - 13))
        label = "Today" if i == 0 else "Tomorrow" if i == 1 else d.isoformat()
        precip_txt = (
            f"~{precip:.1f}mm precip." if precip >= _WET_MM else "no precip expected."
        )
        lines.append(
            f"{label}: {_met_symbol(_symbol(midday[1]))}, "
            f"{round(_c_to_f(min(temps)))}–{round(_c_to_f(max(temps)))}°F, {precip_txt}"
        )

    # Rain windows from the hourly (next_1_hours) span; no probabilities in
    # compact, so _rain_windows labels peaks in mm/h.
    h_times: list[str] = []
    h_amts: list = []
    for dt, e in parsed:
        n1 = _block(e, "next_1_hours").get("details")
        if n1 is None:
            continue
        h_times.append(dt.isoformat())
        h_amts.append(n1.get("precipitation_amount"))
    rain = _rain_windows({
        "time": h_times,
        "precipitation_probability": [None] * len(h_times),
        "precipitation": h_amts,
    })
    if rain is not None:
        lines.append("")
        lines.append(
            "Rain timing (reason from THESE for a plan, not the daily total): "
            + rain
        )
    return "\n".join(lines)


async def _forecast_met_no(
    ctx: ToolContext, lat: float, lon: float, place: str, days: int, tz: ZoneInfo
) -> str:
    # met.no TOS: round coords (helps their cache) and send an identifying UA.
    r = await ctx.http_client.get(
        MET_NO_URL,
        params={"lat": round(lat, 4), "lon": round(lon, 4)},
        headers={"User-Agent": _MET_NO_UA},
        timeout=15,
    )
    r.raise_for_status()
    series = (r.json().get("properties") or {}).get("timeseries") or []
    return _format_met_no(series, place, days, tz)


_FORECAST_PROVIDERS: tuple = (
    ("open-meteo", _forecast_open_meteo),
    ("met.no", _forecast_met_no),
)


async def _forecast_with_failover(
    ctx: ToolContext,
    lat: float,
    lon: float,
    place: str,
    days: int,
    tz: ZoneInfo,
    providers: tuple = _FORECAST_PROVIDERS,
) -> str:
    """First provider that yields a usable forecast wins; a provider error or
    timeout moves down the ladder instead of surfacing to the user."""
    last: Exception | None = None
    for name, fetch in providers:
        try:
            text = await fetch(ctx, lat, lon, place, days, tz)
            if name != providers[0][0]:
                log.warning("weather.provider_fallback", provider=name, place=place)
            return text
        except Exception as exc:
            last = exc
            log.warning("weather.provider_failed", provider=name, error=str(exc))
    raise last if last is not None else RuntimeError("no weather providers")


# --------------------------------------------------------------------------- #
# Last-known-good cache — served ONLY when every provider fails, so an outage
# degrades to slightly-old real data instead of an error string. 30 min keeps
# "Now:" close enough to act on; older than that, the error is more honest.
# --------------------------------------------------------------------------- #

_CACHE_TTL_SECONDS = 30 * 60
_last_good: dict[str, tuple[str, datetime]] = {}


def _cache_key(location: str) -> str:
    return " ".join(location.lower().split())


def _cache_put(location: str, text: str, now: datetime) -> None:
    _last_good[_cache_key(location)] = (text, now)


def _cache_get(
    location: str, now: datetime, ttl: int = _CACHE_TTL_SECONDS
) -> tuple[str, datetime] | None:
    hit = _last_good.get(_cache_key(location))
    if hit is None or (now - hit[1]).total_seconds() > ttl:
        return None
    return hit


def _fmt_clock(dt: datetime, tz: ZoneInfo) -> str:
    local = dt.astimezone(tz)
    h12 = local.hour % 12 or 12
    return f"{h12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def _stale_wrap(text: str, fetched_at: datetime, tz: ZoneInfo) -> str:
    """Label stale data so the model presents it as a last reading, never live."""
    return (
        "[STALE — live weather sources are unreachable; last good reading "
        f"as of {_fmt_clock(fetched_at, tz)}]\n{text}"
    )


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
    now = datetime.now(timezone.utc)

    try:
        hit = await _geocode(ctx, location)
        if hit is None:
            # Both geocoders down looks identical to an unknown place; a cache
            # hit disambiguates — this location string resolved before.
            cached = _cache_get(location, now)
            if cached is not None:
                return _stale_wrap(cached[0], cached[1], tz)
            return (
                f"Couldn't find a location matching '{location}'. Try a simpler "
                "form like 'Brooklyn NY' or a city name."
            )
        lat, lon, place = hit
        text = await _forecast_with_failover(ctx, lat, lon, place, days, tz)
        _cache_put(location, text, now)
        return text
    except Exception as exc:
        log.exception("weather.error", location=location)
        cached = _cache_get(location, now)
        if cached is not None:
            return _stale_wrap(cached[0], cached[1], tz)
        return f"Weather lookup failed: {exc}"
