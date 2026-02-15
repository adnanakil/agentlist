"""Stripe deposit and webhook routes."""

from __future__ import annotations

import uuid

import stripe
import structlog
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import BillingConfig
from ag_common.errors import ValidationError
from ag_common.models import DepositRequest, DepositResponse
from ag_db.session import get_session

from billing.services import stripe as stripe_svc

log = structlog.get_logger()
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_config(request: Request) -> BillingConfig:
    """Retrieve the BillingConfig stored on app state during lifespan."""
    return request.app.state.config


def _parse_account_id(x_account_id: str | None = Header(None)) -> uuid.UUID:
    if not x_account_id:
        raise ValidationError("X-Account-ID header is required")
    try:
        return uuid.UUID(x_account_id)
    except ValueError:
        raise ValidationError("X-Account-ID must be a valid UUID")


# ---------------------------------------------------------------------------
# Deposit — create Stripe checkout session
# ---------------------------------------------------------------------------


class DepositRequestWithEmail(BaseModel):
    """Extends DepositRequest with optional email for Stripe."""
    amount_cents: int
    customer_email: str | None = None


@router.post("/internal/deposit", response_model=DepositResponse)
async def create_deposit(
    body: DepositRequest,
    account_id: uuid.UUID = Depends(_parse_account_id),
    config: BillingConfig = Depends(_get_config),
) -> DepositResponse:
    """Create a Stripe Checkout Session so the consumer can add funds."""
    checkout_url, session_id = await stripe_svc.create_checkout_session(
        account_id=account_id,
        amount_cents=body.amount_cents,
        customer_email=None,
        config=config,
    )
    return DepositResponse(checkout_url=checkout_url, session_id=session_id)


# ---------------------------------------------------------------------------
# Stripe webhook
# ---------------------------------------------------------------------------


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Handle incoming Stripe webhook events.

    1. Verify the event signature.
    2. Check for duplicate event ID (idempotency).
    3. Dispatch based on event type.
    4. Return 200 so Stripe does not retry.
    """
    config: BillingConfig = request.app.state.config
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # Verify webhook signature
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=config.stripe_webhook_secret,
        )
    except stripe.error.SignatureVerificationError:
        log.warning("stripe.webhook_signature_invalid")
        return JSONResponse(status_code=400, content={"error": "Invalid signature"})
    except ValueError:
        log.warning("stripe.webhook_payload_invalid")
        return JSONResponse(status_code=400, content={"error": "Invalid payload"})

    event_id: str = event["id"]
    event_type: str = event["type"]

    log.info("stripe.webhook_received", event_id=event_id, event_type=event_type)

    # Idempotency check
    if await stripe_svc.is_event_processed(session, event_id):
        log.info("stripe.webhook_duplicate", event_id=event_id)
        return JSONResponse(status_code=200, content={"status": "already_processed"})

    # Dispatch
    if event_type == "checkout.session.completed":
        await stripe_svc.handle_checkout_completed(session, event["data"])
    else:
        log.info("stripe.webhook_unhandled_type", event_type=event_type)

    # Record event for idempotency
    await stripe_svc.record_event(session, event_id, event_type)
    await session.commit()

    return JSONResponse(status_code=200, content={"status": "ok"})
