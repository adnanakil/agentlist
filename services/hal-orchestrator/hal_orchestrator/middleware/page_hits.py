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
    r"bot|crawl|spider|slurp|preview|scan|monitor|probe|curl|wget|python-requests|httpx|go-http",
    re.I,
)


def _visitor_hash(ip: str, user_agent: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return hashlib.sha256(f"{ip}|{user_agent}|{day}".encode()).hexdigest()[:16]


async def _record(path: str, referrer: str, user_agent: str, ip: str) -> None:
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
                    visitor_hash=_visitor_hash(ip, user_agent),
                    is_bot=bool(_BOT_RE.search(user_agent)),
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
            asyncio.get_running_loop().create_task(
                _record(
                    request.url.path,
                    request.headers.get("referer", ""),
                    request.headers.get("user-agent", ""),
                    ip,
                )
            )
        return response
