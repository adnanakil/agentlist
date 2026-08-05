"""Server-side page-view recording for the public landing pages.

First-party and cookie-less by design — the landing page promises "never
sold, never ads, never used to train anything", so there is no client-side
tracker to ship. A row is written per successful GET of a public page;
raw IPs are never stored (day-salted hash only, so hashes can't be joined
across days). Recording is fire-and-forget: it must never slow down or
break a page load.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime, timezone

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

import ag_db.session as db_session
from ag_db.models import HalPageHit

log = structlog.get_logger()

TRACKED_PATHS = {"/", "/privacy", "/terms"}

_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|preview|scan|monitor|probe|curl|wget|python|httpx|"
    r"go-http|java|scrapy|measurement|inspection|lighthouse|headless|phantom|"
    r"selenium|censys|zgrab|nuclei|expanse|dataprovider",
    re.I,
)

# Scanners love stale browser UAs; versions this old are extinct among real
# users in 2026, and NT 6.x (Win 7/8) / 32-bit Linux desktops likewise.
_UA_VERSION_RE = re.compile(r"(?:Chrome|Firefox)/(\d+)")
_ANCIENT_PLATFORM_RE = re.compile(r"Windows NT [56]\.|Linux i686")


def _looks_bot(user_agent: str) -> bool:
    if _BOT_RE.search(user_agent):
        return True
    if _ANCIENT_PLATFORM_RE.search(user_agent):
        return True
    m = _UA_VERSION_RE.search(user_agent)
    return bool(m) and int(m.group(1)) < 115


def visitor_hash(ip: str, user_agent: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return hashlib.sha256(f"{ip}|{user_agent}|{day}".encode()).hexdigest()[:16]


_visitor_hash = visitor_hash  # back-compat alias for existing callers

# Landing hero-CTA experiment. The coin flip is a parity bit of the visitor
# hash rather than random(), which buys two things: the same visitor keeps
# their variant across reloads within a day (a reshuffle on refresh would
# smear the two arms together), and the renderer and the page-hit recorder
# derive the SAME variant from the same request without passing state between
# them. Uniform because sha256 hex digits are uniform.
LANDING_VARIANTS = ("a", "b")


def landing_variant(vh: str) -> str:
    """'a' (Text HAL) or 'b' (Text <number>) for a visitor hash. PURE."""
    try:
        return LANDING_VARIANTS[int(vh[-1], 16) & 1]
    except (ValueError, IndexError):
        return LANDING_VARIANTS[0]


async def _record(
    path: str,
    referrer: str,
    user_agent: str,
    ip: str,
    utm_source: str | None = None,
    utm_medium: str | None = None,
    utm_campaign: str | None = None,
    attribution_code: str | None = None,
    variant: str | None = None,
) -> None:
    factory = db_session._session_factory
    if factory is None:
        return
    try:
        async with factory() as session:
            session.add(
                HalPageHit(
                    path=path,
                    referrer=referrer[:2000] or None,
                    user_agent=user_agent[:2000] or None,
                    visitor_hash=visitor_hash(ip, user_agent),
                    is_bot=_looks_bot(user_agent),
                    utm_source=utm_source,
                    utm_medium=utm_medium,
                    utm_campaign=utm_campaign,
                    attribution_code=attribution_code,
                    variant=variant,
                )
            )
            await session.commit()
    except Exception:
        log.exception("page_hits.record_failed", path=path)


class PageHitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if (
            request.method == "GET"
            and request.url.path in TRACKED_PATHS
            and response.status_code == 200
        ):
            # Railway's edge proxy puts the real client in X-Forwarded-For.
            fwd = request.headers.get("x-forwarded-for", "")
            ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "")
            ua = request.headers.get("user-agent", "")
            qp = request.query_params
            # Only "/" carries the hero CTA, so only "/" is in the experiment.
            variant = landing_variant(visitor_hash(ip, ua)) if request.url.path == "/" else None
            asyncio.get_running_loop().create_task(
                _record(
                    request.url.path,
                    request.headers.get("referer", ""),
                    ua,
                    ip,
                    variant=variant,
                    utm_source=(qp.get("utm_source") or "")[:255] or None,
                    utm_medium=(qp.get("utm_medium") or "")[:255] or None,
                    utm_campaign=(qp.get("utm_campaign") or "")[:255] or None,
                    attribution_code=(qp.get("c") or "")[:64] or None,
                )
            )
        return response
