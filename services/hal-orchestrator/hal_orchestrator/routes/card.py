"""GET /card.png — public, HMAC-signed baby status card image.

The live iMessage bridge sends text only (it can't attach files), so HAL puts
this URL in the reply and iMessage renders it inline. The signature scopes each
URL to one silo so cards can't be enumerated; the render is live (current
state) and lightly cached.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.session import get_session
from hal_orchestrator.services.baby_card import render_for_silo, verify_card_token
from hal_orchestrator.state import get_settings

log = structlog.get_logger()


def build_card_router() -> APIRouter:
    router = APIRouter()

    @router.get("/card.png")
    async def card_png(
        s: str,
        sig: str,
        e: int,
        t: str = "",
        session: AsyncSession = Depends(get_session),
    ) -> Response:
        settings = get_settings()
        signing_key = settings.card_signing_key or settings.hal_bridge_secret
        silo = verify_card_token(s, sig, e, signing_key)
        if not silo:
            raise HTTPException(status_code=403, detail="bad signature")
        try:
            png = await render_for_silo(session, silo)
        except Exception:
            log.exception("card.render_failed")
            raise HTTPException(status_code=500, detail="render failed")
        if not png:
            raise HTTPException(status_code=404, detail="no data")
        return Response(
            content=png,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=300"},
        )

    return router
