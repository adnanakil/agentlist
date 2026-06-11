"""Resy client (read-only): venue search, availability, and a deep booking link.

Scope: HAL FINDS tables and hands the user a Resy link to book themselves on
THEIR OWN account. No per-user auth, no stored credentials, no booking on
anyone's behalf. Uses only Resy's public web api_key (swappable via config).

Hardened vs the bespoke bot: all calls funnel through a shared rate limiter +
TTL cache + 419/429/403 backoff.
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlencode

import httpx
import structlog

from ag_common.config import HalOrchestratorConfig

log = structlog.get_logger()

API = "https://api.resy.com"
# Default geo bias for venue search (NYC). Resy's search is geo-weighted.
_GEO = {"latitude": 40.7466, "longitude": -74.0036}

_MIN_INTERVAL = 0.35  # seconds between Resy calls (process-wide)
_rate_lock = asyncio.Lock()
_last_call = 0.0
_cache: dict[str, tuple[float, object]] = {}


async def _throttle() -> None:
    global _last_call
    async with _rate_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.monotonic()


def _cache_get(key: str):
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    return None


def _cache_put(key: str, value, ttl: float) -> None:
    _cache[key] = (time.monotonic() + ttl, value)


def is_configured(settings: HalOrchestratorConfig) -> bool:
    return bool(settings.resy_api_key)


def _headers(settings: HalOrchestratorConfig) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f'ResyAPI api_key="{settings.resy_api_key}"',
        "Origin": "https://resy.com",
        "Referer": "https://resy.com/",
        "X-Origin": "https://resy.com",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.2.1 Safari/605.1.15"
        ),
    }


class ResyError(Exception):
    def __init__(self, kind: str, message: str = ""):
        self.kind = kind  # rate_limited | error
        super().__init__(message or kind)


async def _request(
    client: httpx.AsyncClient,
    settings: HalOrchestratorConfig,
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
    retries: int = 2,
) -> httpx.Response:
    url = f"{API}{path}"
    for attempt in range(retries + 1):
        await _throttle()
        try:
            resp = await client.request(
                method, url, headers=_headers(settings),
                params=params, json=json_body, timeout=30,
            )
        except Exception as exc:
            if attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            raise ResyError("error", str(exc))
        if resp.status_code in (419, 429, 403):
            if attempt < retries:
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            raise ResyError("rate_limited", f"Resy throttled ({resp.status_code})")
        return resp
    raise ResyError("error", "exhausted retries")


def build_booking_url(venue: dict, date: str | None = None, party_size: int | None = None) -> str:
    """Public Resy venue page (date/party pre-filled) — the user books here on
    their own account."""
    city = venue.get("city_slug") or "new-york-ny"
    slug = venue.get("url_slug")
    base = f"https://resy.com/cities/{city}/venues/{slug}"
    q = {}
    if date:
        q["date"] = date
    if party_size:
        q["seats"] = party_size
    return f"{base}?{urlencode(q)}" if q else base


async def search_venues(
    client: httpx.AsyncClient, settings: HalOrchestratorConfig, query: str
) -> list[dict]:
    ck = f"search:{query.lower().strip()}"
    cached = _cache_get(ck)
    if cached is not None:
        return cached  # type: ignore[return-value]
    resp = await _request(
        client, settings, "POST", "/3/venuesearch/search",
        json_body={"query": query, "geo": _GEO},
    )
    out: list[dict] = []
    if resp.status_code == 200:
        for h in (resp.json().get("search", {}) or {}).get("hits", []):
            hid = h.get("id")
            loc = h.get("location") or {}
            out.append(
                {
                    "venue_id": hid.get("resy") if isinstance(hid, dict) else hid,
                    "name": h.get("name"),
                    "location": loc.get("name") if isinstance(loc, dict) else None,
                    "url_slug": h.get("url_slug"),
                    "city_slug": loc.get("url_slug") if isinstance(loc, dict) else None,
                    "cuisine": h.get("cuisine"),
                }
            )
    _cache_put(ck, out, 300)
    return out


async def get_availability(
    client: httpx.AsyncClient,
    settings: HalOrchestratorConfig,
    venue_id: str,
    date: str,
    party_size: int,
) -> list[dict]:
    """Open slots (exact time + table type) for a venue/date/party. No
    'closest time' snapping — return the real options."""
    resp = await _request(
        client, settings, "GET", "/4/find",
        params={"day": date, "lat": "0", "long": "0",
                "party_size": str(party_size), "venue_id": str(venue_id)},
    )
    if resp.status_code != 200:
        raise ResyError("error", f"availability {resp.status_code}")
    venues = (resp.json().get("results", {}) or {}).get("venues", [])
    out: list[dict] = []
    if venues:
        for s in venues[0].get("slots", []):
            cfg = s.get("config", {}) or {}
            out.append({"time": (s.get("date", {}) or {}).get("start"), "type": cfg.get("type")})
    return out


async def get_calendar(
    client: httpx.AsyncClient,
    settings: HalOrchestratorConfig,
    venue_id: str,
    party_size: int,
    start: str,
    end: str,
) -> list[str]:
    ck = f"cal:{venue_id}:{party_size}:{start}:{end}"
    cached = _cache_get(ck)
    if cached is not None:
        return cached  # type: ignore[return-value]
    resp = await _request(
        client, settings, "GET", "/4/venue/calendar",
        params={"venue_id": str(venue_id), "num_seats": str(party_size),
                "start_date": start, "end_date": end},
    )
    days: list[str] = []
    if resp.status_code == 200:
        for d in resp.json().get("scheduled", []):
            if d.get("inventory", {}).get("reservation") == "available":
                days.append(d.get("date"))
    _cache_put(ck, days, 120)
    return days
