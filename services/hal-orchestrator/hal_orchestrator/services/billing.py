"""Stripe billing for HAL — the pay -> auto-unlock loop.

Flow:
  1. A capped user gets a funding link: the configured Stripe Payment Link with a
     signed `client_reference_id` appended that binds the payment to their silo.
  2. They pay (Apple Pay one-tap on iPhone, in the Stripe checkout page).
  3. Stripe POSTs `checkout.session.completed` to /api/stripe/webhook.
  4. We verify the signature, recover the silo from client_reference_id, lift the
     cap (usage.set_plan), and text them a confirmation.

No outbound Stripe API calls and no Stripe SDK dependency: the pay link is static
(carrying only the signed ref), and the inbound webhook signature is verified with
the documented HMAC-SHA256 `v1` scheme. `stripe_secret_key` is therefore optional;
only `stripe_webhook_secret` is needed to accept the webhook.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import structlog

from hal_orchestrator.services.crypto import sign_billing_ref, verify_billing_ref

log = structlog.get_logger()

# Stripe's default webhook replay tolerance.
WEBHOOK_TOLERANCE_SECONDS = 300

UNLOCK_MESSAGE = (
    "You're all set — unlimited messages unlocked. Thanks for supporting HAL! 🎉"
)


def _downgrade_message(settings, silo: str) -> str:
    limit = getattr(settings, "free_message_limit", 0)
    tier = f" ({limit} messages a month)" if limit and limit > 0 else ""
    msg = f"Your HAL subscription ended — you're back on the free plan{tier}."
    pay = pay_url_for(settings, silo)
    if pay:
        msg += f" Resubscribe anytime:\n{pay}"
    return msg


def is_configured(settings) -> bool:
    """True when the pay -> unlock webhook can be accepted."""
    return bool(getattr(settings, "stripe_webhook_secret", ""))


def pay_url_for(settings, silo: str) -> str | None:
    """The funding link for `silo`: the Payment Link + a signed client_reference_id
    that binds a completed payment back to this user. None if no link is set."""
    base = getattr(settings, "payment_url", "")
    if not base:
        return None
    ref = sign_billing_ref(settings, silo)
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}client_reference_id={ref}"


def verify_webhook(
    settings, payload: bytes | str, sig_header: str,
    tolerance: int = WEBHOOK_TOLERANCE_SECONDS,
) -> dict | None:
    """Verify a Stripe webhook signature and return the parsed event, or None.

    Implements Stripe's scheme: the Stripe-Signature header is `t=<ts>,v1=<sig>...`;
    the signed payload is `"{ts}.".encode() + body`, HMAC-SHA256'd with the endpoint
    secret. Rejects a stale timestamp (replay) and any signature mismatch.
    """
    secret = getattr(settings, "stripe_webhook_secret", "")
    if not secret or not sig_header:
        return None

    ts: str | None = None
    v1: list[str] = []
    for part in sig_header.split(","):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.strip()
        if key == "t":
            ts = val.strip()
        elif key == "v1":
            v1.append(val.strip())
    if not ts or not v1:
        return None
    try:
        ts_int = int(ts)
    except ValueError:
        return None
    if abs(int(time.time()) - ts_int) > tolerance:
        log.warning("stripe.webhook_stale", ts=ts_int)
        return None

    if isinstance(payload, str):
        payload = payload.encode()
    signed = ts.encode() + b"." + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in v1):
        log.warning("stripe.webhook_bad_signature")
        return None

    try:
        return json.loads(payload.decode("utf-8"))
    except Exception:
        log.warning("stripe.webhook_bad_json")
        return None


async def handle_event(session, settings, event: dict) -> str | None:
    """Process a verified Stripe event. Returns the affected silo, or None.

    - checkout.session.completed → unlock the silo from client_reference_id and
      record the Stripe customer/subscription ids (idempotent: a repeat delivery
      for an already-unlimited user skips the confirmation text).
    - customer.subscription.deleted → the subscription was cancelled or lapsed;
      map it back to the silo via the stored ids and downgrade to the free tier.
    """
    if not isinstance(event, dict):
        return None
    etype = event.get("type")
    obj = ((event.get("data") or {}).get("object")) or {}

    if etype == "checkout.session.completed":
        return await _handle_checkout(session, settings, obj)
    if etype == "customer.subscription.deleted":
        return await _handle_cancel(session, settings, obj)

    log.info("stripe.unhandled_type", type=etype)
    return None


async def _alert_unmatched_payment(settings, obj: dict, *, has_ref: bool) -> None:
    """A REAL payment we couldn't tie to a user (missing/invalid
    client_reference_id). Ping the admin so a paying user is never silently
    stranded — this is the exact failure that hid a broken pay link for a full
    billing cycle (the bridge was mangling `client_reference_id` -> null). Best
    effort: an alert must never turn a 200 into a webhook retry storm.
    """
    admin = getattr(settings, "admin_phone", "")
    if not admin:
        return
    try:
        details = obj.get("customer_details") or {}
        amount = obj.get("amount_total")
        amt = f"${amount / 100:.2f}" if isinstance(amount, (int, float)) else "?"
        who = details.get("email") or details.get("name") or obj.get("customer") or "unknown"
        reason = "reference didn't verify" if has_ref else "no client_reference_id on the session"
        import hal_orchestrator.state as state

        await state.outbox.put(
            {
                "to": admin,
                "text": (
                    f"⚠️ Stripe payment ({amt}) I couldn't match to a user — {reason}. "
                    f"Payer: {who}. Session {obj.get('id', '?')}. "
                    "Unlock them manually and check the pay link."
                ),
            }
        )
        log.warning("stripe.unmatched_payment_alerted", amount=amt, has_ref=has_ref)
    except Exception:
        log.exception("stripe.unmatched_alert_failed")


async def _handle_checkout(session, settings, obj: dict) -> str | None:
    ref = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("silo")
    silo = verify_billing_ref(settings, ref) if ref else None
    if not silo:
        log.warning("stripe.no_valid_silo", has_ref=bool(ref))
        await _alert_unmatched_payment(settings, obj, has_ref=bool(ref))
        return None

    from hal_orchestrator.services.profiles import get_profile
    from hal_orchestrator.services.usage import set_plan

    profile = await get_profile(session, silo)
    already = bool(((profile.get("extra_data") or {}).get("plan") or {}).get("unlimited"))

    await set_plan(
        session,
        silo,
        unlimited=True,
        stripe_customer_id=obj.get("customer"),
        stripe_subscription_id=obj.get("subscription"),
    )

    if not already:
        import hal_orchestrator.state as state

        await state.outbox.put({"to": silo, "text": UNLOCK_MESSAGE})
        log.info("stripe.unlocked", silo=silo)
    else:
        log.info("stripe.unlock_repeat", silo=silo)
    return silo


async def _handle_cancel(session, settings, obj: dict) -> str | None:
    from hal_orchestrator.services.profiles import find_by_stripe
    from hal_orchestrator.services.usage import downgrade_to_free

    silo = await find_by_stripe(
        session,
        subscription_id=obj.get("id"),
        customer_id=obj.get("customer"),
    )
    if not silo:
        log.info("stripe.cancel_no_match", has_sub=bool(obj.get("id")))
        return None

    await downgrade_to_free(session, silo)
    import hal_orchestrator.state as state

    await state.outbox.put({"to": silo, "text": _downgrade_message(settings, silo)})
    log.info("stripe.downgraded", silo=silo)
    return silo
