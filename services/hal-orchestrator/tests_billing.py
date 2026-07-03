"""Tests for the Stripe pay -> auto-unlock loop (services/billing.py + crypto).

Covers: signed billing-ref round-trip (Stripe-safe charset, tamper/expiry),
pay_url_for, manual webhook signature verification (happy / tampered / stale /
missing), and handle_event unlocking a silo + idempotent re-delivery.

Run: python3 services/hal-orchestrator/tests_billing.py
"""

import asyncio
import hashlib
import hmac
import json
import os
import re
import sys
import time
from types import SimpleNamespace

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hal_orchestrator.services.billing as billing
import hal_orchestrator.services.usage as usage
from hal_orchestrator.services.billing import (
    handle_event,
    is_configured,
    pay_url_for,
    verify_webhook,
)
from hal_orchestrator.services.crypto import sign_billing_ref, verify_billing_ref

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        failures.append(name)


ENC_KEY = "Zk1s2j3k4l5m6n7o8p9q0r1s2t3u4v5w6x7y8z9A0B0="  # any string; only used as HMAC key


def _settings(**over):
    base = dict(
        encryption_key=ENC_KEY,
        payment_url="https://buy.stripe.com/test_123",
        stripe_webhook_secret="whsec_testsecret",
        admin_phone="",
        free_message_limit=3,
    )
    base.update(over)
    return SimpleNamespace(**base)


# --- Signed billing ref ---------------------------------------------------- #
print("sign_billing_ref / verify_billing_ref:")
s = _settings()
silo = "+15550001234"
ref = sign_billing_ref(s, silo)
check("round-trips to the silo", verify_billing_ref(s, ref) == silo)
check(
    "Stripe-safe charset ([A-Za-z0-9-_] only)",
    re.fullmatch(r"[A-Za-z0-9\-_]+", ref) is not None,
    detail=ref,
)
check("tampered ref rejected", verify_billing_ref(s, ref[:-1] + ("0" if ref[-1] != "0" else "1")) is None)
check("garbage ref rejected", verify_billing_ref(s, "nope") is None)
check("empty ref rejected", verify_billing_ref(s, "") is None)
check(
    "wrong key rejected",
    verify_billing_ref(_settings(encryption_key="different-key"), ref) is None,
)
expired = sign_billing_ref(s, silo, ttl=-10)
check("expired ref rejected", verify_billing_ref(s, expired) is None)


# --- pay_url_for ----------------------------------------------------------- #
print("pay_url_for:")
url = pay_url_for(s, silo)
check("appends client_reference_id", url and "client_reference_id=" in url and url.startswith("https://buy.stripe.com/"))
check("no payment_url -> None", pay_url_for(_settings(payment_url=""), silo) is None)
# The ref in the URL must verify back to the silo.
ref_in_url = url.split("client_reference_id=")[1]
check("url ref verifies back to silo", verify_billing_ref(s, ref_in_url) == silo)
# & separator when the base already has a query.
url2 = pay_url_for(_settings(payment_url="https://buy.stripe.com/x?foo=1"), silo)
check("uses & when base has a query", "?foo=1&client_reference_id=" in url2)


# --- is_configured --------------------------------------------------------- #
print("is_configured:")
check("configured when webhook secret set", is_configured(s))
check("not configured without webhook secret", not is_configured(_settings(stripe_webhook_secret="")))


# --- Webhook signature verification ---------------------------------------- #
print("verify_webhook:")


def _sign(secret, payload_bytes, ts=None):
    ts = ts or int(time.time())
    signed = f"{ts}.".encode() + payload_bytes
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


event_obj = {
    "id": "evt_1",
    "type": "checkout.session.completed",
    "data": {"object": {"client_reference_id": ref}},
}
body = json.dumps(event_obj).encode()
good_header = _sign("whsec_testsecret", body)

check("valid signature parses the event", verify_webhook(s, body, good_header) == event_obj)
check("tampered body rejected", verify_webhook(s, body + b" ", good_header) is None)
check("wrong secret rejected", verify_webhook(_settings(stripe_webhook_secret="whsec_other"), body, good_header) is None)
check("missing header rejected", verify_webhook(s, body, "") is None)
check("no webhook secret -> None", verify_webhook(_settings(stripe_webhook_secret=""), body, good_header) is None)
stale_header = _sign("whsec_testsecret", body, ts=int(time.time()) - 10_000)
check("stale timestamp (replay) rejected", verify_webhook(s, body, stale_header) is None)


# --- handle_event: unlock + idempotency ------------------------------------ #
print("handle_event:")
import hal_orchestrator.state as state

STORE: dict = {}


async def _fake_get_profile(session, sl):
    return {"phone": sl, "extra_data": dict(STORE.get(sl, {}))}


async def _fake_update_profile(session, sl, **fields):
    extra = dict(STORE.get(sl, {}))
    for k in ("usage", "plan"):
        if k in fields:
            extra[k] = fields[k]
    STORE[sl] = extra
    return {"phone": sl, "extra_data": extra}


# billing.handle_event imports get_profile/set_plan from their modules at call
# time; set_plan lives in usage and uses usage.update_profile. Patch both layers.
usage.get_profile = _fake_get_profile
usage.update_profile = _fake_update_profile
import hal_orchestrator.services.profiles as profiles_mod

profiles_mod.get_profile = _fake_get_profile  # for billing's own get_profile import


async def _fake_find_by_stripe(session, *, customer_id=None, subscription_id=None):
    for sl, extra in STORE.items():
        plan = extra.get("plan") or {}
        if subscription_id and plan.get("stripe_subscription_id") == subscription_id:
            return sl
        if customer_id and plan.get("stripe_customer_id") == customer_id:
            return sl
    return None


profiles_mod.find_by_stripe = _fake_find_by_stripe

# drain outbox
while not state.outbox.empty():
    state.outbox.get_nowait()

silo_out = asyncio.run(handle_event(None, s, event_obj))
check("unlocks the paying silo", silo_out == silo)
check("plan set to unlimited", STORE.get(silo, {}).get("plan", {}).get("unlimited") is True)
notes = []
while not state.outbox.empty():
    notes.append(state.outbox.get_nowait())
check("confirmation text queued to the user", any(n["to"] == silo and "unlocked" in n["text"] for n in notes))

# Re-delivery of the same event: still returns silo, but does NOT re-text.
silo_out2 = asyncio.run(handle_event(None, s, event_obj))
redelivery_notes = []
while not state.outbox.empty():
    redelivery_notes.append(state.outbox.get_nowait())
check("idempotent re-delivery unlocks again", silo_out2 == silo)
check("no duplicate confirmation text", len(redelivery_notes) == 0)

# Event with an invalid/forged ref → ignored.
bad_event = {
    "id": "evt_2",
    "type": "checkout.session.completed",
    "data": {"object": {"client_reference_id": "forged"}},
}
check("forged client_reference_id ignored", asyncio.run(handle_event(None, s, bad_event)) is None)

# Unhandled event type → ignored.
other = {"id": "evt_3", "type": "payment_intent.created", "data": {"object": {}}}
check("unhandled event type ignored", asyncio.run(handle_event(None, s, other)) is None)


# --- Subscription lifecycle: checkout stores ids, cancel downgrades --------- #
print("subscription lifecycle (checkout -> cancel):")
STORE.clear()
while not state.outbox.empty():
    state.outbox.get_nowait()
sub_silo = "+15550007777"
sub_ref = sign_billing_ref(s, sub_silo)
checkout_evt = {
    "id": "evt_sub1",
    "type": "checkout.session.completed",
    "data": {"object": {
        "client_reference_id": sub_ref,
        "mode": "subscription",
        "customer": "cus_ABC123",
        "subscription": "sub_XYZ789",
    }},
}
asyncio.run(handle_event(None, s, checkout_evt))
plan = STORE.get(sub_silo, {}).get("plan", {})
check("checkout unlocks the subscriber", plan.get("unlimited") is True)
check("stores stripe customer id", plan.get("stripe_customer_id") == "cus_ABC123")
check("stores stripe subscription id", plan.get("stripe_subscription_id") == "sub_XYZ789")

# The subscriber is unlimited -> enforce_quota lets them through past the cap.
STORE[sub_silo]["usage"] = {"period": "2099-01", "count": 9999}
r = asyncio.run(usage.enforce_quota(None, sub_silo, _settings(free_message_limit=3)))
check("active subscriber bypasses the cap", r.allowed)

# Cancellation: subscription.deleted maps back via the stored ids and downgrades.
while not state.outbox.empty():
    state.outbox.get_nowait()
cancel_evt = {
    "id": "evt_sub2",
    "type": "customer.subscription.deleted",
    "data": {"object": {"id": "sub_XYZ789", "customer": "cus_ABC123"}},
}
downgraded = asyncio.run(handle_event(None, s, cancel_evt))
check("cancel maps back to the right silo", downgraded == sub_silo)
check("plan downgraded (not unlimited)", STORE[sub_silo]["plan"].get("unlimited") is False)
notes = []
while not state.outbox.empty():
    notes.append(state.outbox.get_nowait())
check("downgrade texts the user with a resubscribe link", any(n["to"] == sub_silo and "free plan" in n["text"] for n in notes))

# After downgrade, the free cap applies again (current period, at the limit).
_now_period = __import__("datetime").datetime.now(
    __import__("datetime").timezone.utc
).strftime("%Y-%m")
STORE[sub_silo]["usage"] = {"period": _now_period, "count": 3}
r = asyncio.run(usage.enforce_quota(None, sub_silo, _settings(free_message_limit=3)))
check("downgraded user is capped again", not r.allowed)

# A cancel for an unknown subscription is a no-op.
unknown_cancel = {
    "id": "evt_sub3",
    "type": "customer.subscription.deleted",
    "data": {"object": {"id": "sub_UNKNOWN", "customer": "cus_UNKNOWN"}},
}
check("cancel for unknown sub ignored", asyncio.run(handle_event(None, s, unknown_cancel)) is None)


if failures:
    print(f"\n{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("\nAll billing tests passed.")
