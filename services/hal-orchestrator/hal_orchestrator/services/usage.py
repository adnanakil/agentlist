"""Per-user message quota — a free monthly cap, then a funding prompt.

New users get `settings.free_message_limit` user-initiated messages per calendar
month (per 1:1 silo). Over the cap, the message route short-circuits BEFORE the
model runs and replies with a funding message (a Stripe/payment link that offers
Apple Pay one-tap on iPhone). A paid user's profile carries a `plan` that lifts
or removes the cap.

What is NOT metered: heartbeats / proactive turns (HAL-initiated, `internal`),
group chats (shared, not a billing identity), and the admin phone. The counter
lives in `profile.extra_data["usage"]` (no schema migration), and same-silo
messages are serialized by the bridge, so the read-modify-write is race-safe in
practice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import structlog

from hal_orchestrator.services.identity import normalize_handle
from hal_orchestrator.services.profiles import get_profile, update_profile

log = structlog.get_logger()


@dataclass
class QuotaResult:
    allowed: bool
    message: str = ""  # funding message when blocked
    count: int = 0
    limit: int = 0


def _period_key(now: datetime) -> str:
    return now.strftime("%Y-%m")


def is_metered(silo: str, is_group: bool, internal: bool, settings) -> bool:
    """Only real, user-initiated 1:1 turns from non-admin users count."""
    if is_group or internal:
        return False
    if not settings.free_message_limit or settings.free_message_limit <= 0:
        return False
    admin = normalize_handle(getattr(settings, "admin_phone", "") or "")
    return not (admin and silo == admin)


def funding_message(settings, limit: int, pay_url: str | None = None) -> str:
    # pay_url (a per-user Stripe link with a signed client_reference_id) wins over
    # the static settings.payment_url so a completed payment maps back to this user.
    url = pay_url or getattr(settings, "payment_url", "")
    base = f"You've reached your free limit of {limit} messages this month. "
    if url:
        return (
            base
            + "To keep going, add credit here (quick — and it works with Apple "
            f"Pay on your iPhone):\n{url}\n\n"
            "Your free messages reset on the 1st."
        )
    return (
        base
        + "Paid plans are landing any day now — you'll be back up shortly. "
        "Your free messages reset on the 1st."
    )


async def _plan_limit(extra: dict, settings) -> int | None:
    """Resolve the effective cap from the user's plan. None -> unlimited."""
    plan = extra.get("plan") or {}
    if plan.get("unlimited"):
        return None
    plan_limit = plan.get("limit")
    if isinstance(plan_limit, int) and plan_limit > 0:
        return plan_limit
    return settings.free_message_limit


async def _notify_admin_once(session, silo: str, settings, usage: dict, period: str) -> None:
    """Ping the admin the first time a user hits the wall in a period, so an
    engaged user hitting the paywall is a signal you can act on. Once per
    period, tracked in usage['capped_notified']."""
    if not getattr(settings, "admin_phone", ""):
        return
    if usage.get("capped_notified") == period:
        return
    import hal_orchestrator.state as state

    await state.outbox.put(
        {
            "to": settings.admin_phone,
            "text": f"💰 {silo} hit the free message cap ({period}). Good moment to convert them.",
        }
    )
    await update_profile(session, silo, usage={**usage, "capped_notified": period})


async def enforce_quota(session, silo: str, settings) -> QuotaResult:
    """Check the silo's monthly quota and RESERVE one message if allowed.

    Call only for metered turns (see is_metered). Returns allowed=False with a
    funding message when the cap is reached; otherwise increments the counter.
    """
    profile = await get_profile(session, silo)
    extra = profile.get("extra_data") or {}

    limit = await _plan_limit(extra, settings)
    if limit is None:  # paid / unlimited
        return QuotaResult(allowed=True)

    now = datetime.now(timezone.utc)
    period = _period_key(now)
    usage = extra.get("usage") or {}
    count = usage.get("count", 0) if usage.get("period") == period else 0

    if count >= limit:
        await _notify_admin_once(session, silo, settings, usage, period)
        log.info("usage.capped", silo=silo, count=count, limit=limit, period=period)
        return QuotaResult(
            allowed=False,
            message=funding_message(settings, limit),
            count=count,
            limit=limit,
        )

    # Reserve one. Preserve any capped_notified marker from a prior period reset.
    new_usage = {"period": period, "count": count + 1}
    if usage.get("capped_notified") == period:
        new_usage["capped_notified"] = period
    await update_profile(session, silo, usage=new_usage)
    return QuotaResult(allowed=True, count=count + 1, limit=limit)


async def set_plan(
    session,
    silo: str,
    *,
    unlimited: bool = True,
    limit: int = 0,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
) -> dict:
    """Grant/adjust a user's plan (called when they pay). Also resets the
    current period's counter so they're unblocked immediately. The Stripe ids,
    when given, are stored so a later subscription webhook (cancel/lapse) can map
    back to this silo (see profiles.find_by_stripe). Returns the plan."""
    plan: dict = {"unlimited": True} if (unlimited and limit <= 0) else {
        "unlimited": False,
        "limit": limit,
    }
    if stripe_customer_id:
        plan["stripe_customer_id"] = stripe_customer_id
    if stripe_subscription_id:
        plan["stripe_subscription_id"] = stripe_subscription_id
    now = datetime.now(timezone.utc)
    await update_profile(
        session,
        normalize_handle(silo),
        plan=plan,
        usage={"period": _period_key(now), "count": 0},
    )
    log.info("usage.plan_set", silo=silo, unlimited=plan.get("unlimited"))
    return plan


async def downgrade_to_free(session, silo: str) -> dict:
    """Drop a user back to the free tier (subscription cancelled/lapsed). Keeps
    any stored Stripe ids for audit and preserves the usage counter — this is a
    downgrade, not a reset."""
    sl = normalize_handle(silo)
    profile = await get_profile(session, sl)
    plan = dict((profile.get("extra_data") or {}).get("plan") or {})
    plan["unlimited"] = False
    plan.pop("limit", None)
    await update_profile(session, sl, plan=plan)
    log.info("usage.downgraded", silo=sl)
    return plan
