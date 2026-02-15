"""Stripe integration — checkout sessions and webhook handling."""

from __future__ import annotations

import uuid

import stripe
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import BillingConfig
from ag_db.models import StripeEvent

from billing.services import ledger

log = structlog.get_logger()


async def create_checkout_session(
    account_id: uuid.UUID,
    amount_cents: int,
    customer_email: str | None,
    config: BillingConfig,
) -> tuple[str, str]:
    """Create a Stripe Checkout Session for a one-time deposit.

    Returns:
        A tuple of (checkout_url, session_id).
    """
    stripe.api_key = config.stripe_secret_key

    checkout = stripe.checkout.Session.create(
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": amount_cents,
                    "product_data": {
                        "name": "AgentGate Balance Deposit",
                        "description": f"Add ${amount_cents / 100:.2f} to your AgentGate balance",
                    },
                },
                "quantity": 1,
            }
        ],
        metadata={
            "account_id": str(account_id),
            "amount_cents": str(amount_cents),
        },
        customer_email=customer_email,
        success_url=config.stripe_success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=config.stripe_cancel_url,
    )

    log.info(
        "stripe.checkout_created",
        account_id=str(account_id),
        amount_cents=amount_cents,
        session_id=checkout.id,
    )

    return checkout.url, checkout.id


async def handle_checkout_completed(
    session: AsyncSession,
    event_data: dict,
) -> None:
    """Process a checkout.session.completed webhook event.

    1. Extract account_id from metadata.
    2. Extract amount from amount_total.
    3. Call ledger.deposit() to credit the consumer's balance.
    """
    checkout_obj = event_data.get("object", event_data)

    metadata = checkout_obj.get("metadata", {})
    account_id_str = metadata.get("account_id")
    if not account_id_str:
        log.error("stripe.checkout_completed_missing_account_id", event_data=event_data)
        return

    account_id = uuid.UUID(account_id_str)
    amount_cents = checkout_obj.get("amount_total", 0)
    payment_intent_id = checkout_obj.get("payment_intent")

    if amount_cents <= 0:
        log.error(
            "stripe.checkout_completed_invalid_amount",
            account_id=str(account_id),
            amount_cents=amount_cents,
        )
        return

    await ledger.deposit(
        session=session,
        account_id=account_id,
        amount_cents=amount_cents,
        stripe_payment_intent_id=payment_intent_id,
    )

    log.info(
        "stripe.checkout_completed",
        account_id=str(account_id),
        amount_cents=amount_cents,
        payment_intent_id=payment_intent_id,
    )


async def is_event_processed(
    session: AsyncSession,
    event_id: str,
) -> bool:
    """Check whether we have already processed a Stripe event (idempotency)."""
    stmt = select(StripeEvent).where(StripeEvent.id == event_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def record_event(
    session: AsyncSession,
    event_id: str,
    event_type: str,
) -> None:
    """Persist a Stripe event ID so we never process it twice."""
    event = StripeEvent(id=event_id, event_type=event_type)
    session.add(event)
    await session.flush()
