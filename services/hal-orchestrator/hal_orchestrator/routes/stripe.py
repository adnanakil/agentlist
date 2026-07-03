"""POST /api/stripe/webhook — Stripe payment webhook (pay -> auto-unlock).

Verifies the Stripe signature, recovers the paying user's silo from the signed
client_reference_id, and lifts their message cap. Returns 200 on success so
Stripe stops retrying; 400 on a bad signature; 503 when billing isn't configured.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.session import get_session
from hal_orchestrator.services import billing
from hal_orchestrator.state import get_settings

log = structlog.get_logger()


def build_stripe_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/stripe/webhook")
    async def stripe_webhook(
        request: Request,
        session: AsyncSession = Depends(get_session),
    ) -> JSONResponse:
        settings = get_settings()
        if not billing.is_configured(settings):
            return JSONResponse(status_code=503, content={"error": "billing not configured"})

        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")
        event = billing.verify_webhook(settings, payload, sig)
        if event is None:
            return JSONResponse(status_code=400, content={"error": "invalid signature"})

        log.info("stripe.webhook_received", event_id=event.get("id"), type=event.get("type"))
        try:
            silo = await billing.handle_event(session, settings, event)
            await session.commit()
        except Exception:
            # Return 500 so Stripe retries — better than silently dropping a paid
            # unlock. handle_event is idempotent, so a retry is safe.
            log.exception("stripe.webhook_handler_failed", event_id=event.get("id"))
            return JSONResponse(status_code=500, content={"error": "handler error"})

        return JSONResponse(status_code=200, content={"status": "ok", "unlocked": bool(silo)})

    return router
