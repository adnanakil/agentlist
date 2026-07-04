"""Google OAuth callback — the public landing point users hit after consenting.

Verifies the signed state (which silo started the flow), exchanges the code for
tokens, stores them encrypted for that silo, flips profile.google_connected,
and shows a plain confirmation page telling the user to return to iMessage.
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.session import get_session

from hal_orchestrator.services import google as gsvc
from hal_orchestrator.services.first_win import run_first_win
from hal_orchestrator.services.profiles import get_profile, update_profile
from hal_orchestrator.state import get_http_client, get_settings

log = structlog.get_logger()


def _page(title: str, body: str) -> HTMLResponse:
    html = f"""<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>
body{{font-family:-apple-system,system-ui,sans-serif;background:#f5f5f7;margin:0;
display:flex;min-height:100vh;align-items:center;justify-content:center;color:#1d1d1f}}
.card{{background:#fff;border-radius:18px;padding:40px 32px;max-width:380px;text-align:center;
box-shadow:0 4px 24px rgba(0,0,0,.08)}}h1{{font-size:22px;margin:0 0 8px}}p{{color:#6e6e73;line-height:1.5}}
.e{{font-size:46px;margin-bottom:8px}}</style></head>
<body><div class="card">{body}</div></body></html>"""
    return HTMLResponse(html)


def build_google_router() -> APIRouter:
    router = APIRouter()

    @router.get("/connect/{token}")
    async def connect_start(token: str):
        """Short, iMessage-safe entry point: HAL texts /connect/<signed-token>
        (no giant Google URL with an embedded domain for iMessage to truncate),
        we verify the token -> silo and 302 to the real Google consent URL."""
        settings = get_settings()
        silo = gsvc.verify_state(settings, token)
        if not silo:
            return _page(
                "Link expired",
                '<div class="e">⏱️</div><h1>Link expired</h1>'
                "<p>These links are valid for 10 minutes. Text HAL "
                '"connect google" for a new one.</p>',
            )
        return RedirectResponse(gsvc.build_auth_url(settings, silo), status_code=302)

    @router.get("/api/google/callback")
    async def google_callback(
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
        session: AsyncSession = Depends(get_session),
    ) -> HTMLResponse:
        settings = get_settings()
        http_client = get_http_client()

        if error:
            return _page(
                "Connection cancelled",
                '<div class="e">✋</div><h1>Cancelled</h1>'
                "<p>No access was granted. You can text HAL to try again anytime.</p>",
            )
        if not code or not state:
            return _page(
                "Invalid link",
                '<div class="e">⚠️</div><h1>Invalid link</h1>'
                "<p>This link is missing information. Ask HAL for a fresh one.</p>",
            )

        silo = gsvc.verify_state(settings, state)
        if not silo:
            return _page(
                "Link expired",
                '<div class="e">⏱️</div><h1>Link expired</h1>'
                "<p>These links are valid for 10 minutes. Text HAL "
                '"connect google" for a new one.</p>',
            )

        token_resp = await gsvc.exchange_code(http_client, settings, code)
        if not token_resp:
            return _page(
                "Something went wrong",
                '<div class="e">😕</div><h1>Couldn’t connect</h1>'
                "<p>Google didn’t complete the handshake. Please try again.</p>",
            )

        # Was this the FIRST-ever connect? (Scope-upgrade reconnects shouldn't
        # re-trigger the first-win scan.)
        first_connect = not (await get_profile(session, silo)).get("google_connected")

        email = await gsvc.save_tokens(
            session, settings, http_client, silo, token_resp
        )
        await update_profile(session, silo, google_connected=True)
        await session.commit()
        log.info(
            "google.connected",
            silo=silo,
            email=email if settings.log_message_content else bool(email),
            first=first_connect,
        )

        # First win: HAL just gained calendar+inbox sight — immediately scan
        # and text ONE useful concrete thing, so the connection pays off while
        # the user is still looking at their phone. Fire-and-forget.
        if first_connect:
            asyncio.create_task(run_first_win(settings, http_client, silo))

        who = f" as {email}" if email else ""
        return _page(
            "Connected",
            f'<div class="e">✅</div><h1>Google connected</h1>'
            f"<p>HAL can now read your calendar and Gmail{who}. "
            "Head back to iMessage — you’re all set.</p>",
        )

    return router
