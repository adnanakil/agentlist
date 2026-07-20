"""User profile CRUD (Postgres)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalUserProfile

log = structlog.get_logger()

# Sparse, free-text-ish onboarding fields that live in the extra_data JSONB
# (no dedicated columns). Writes to these keys via update_profile are merged
# into extra_data; get_profile surfaces them as top-level dict keys so callers
# (build_user_context, the contacts tool) read them like any other field.
EXTRA_KEYS = (
    "timezone",
    "home_location",
    "work_location",
    "google_offered",
    # Onboarding ask-decay + funnel (all JSONB, no columns). asked_* are per-fact
    # ask counts (incremented in the message route, one per real turn); after the
    # cap the onboarding flow skips that fact permanently. google_disconnected is
    # set when a user disconnects Google so the offer step never re-pitches.
    # onboarding_events is the queryable funnel timeline; onboarded_at stamps
    # completion. See prompts/system.py (next_onboarding_step / compute_onboarding_progress).
    "asked_name",
    "asked_timezone",
    "asked_home",
    "asked_work",
    # Parent track (beachhead onboarding — ONBOARDING.md): which onboarding
    # track this silo runs ("parent" skips home/work/google entirely), the
    # acquisition code parsed from the landing prefill, and the parent-track
    # ask counters (baby = name+age, city = tz+home in one ask).
    "onboarding_track",
    "acquisition_source",
    "asked_baby",
    "asked_city",
    # C3 forget-me: ISO timestamp set when the user texts "forget me"; the
    # "delete everything" confirm must arrive within 48h (routes/message.py).
    "forget_pending",
    # Membership boundary (GROUP silos only — services/membership.py):
    # member_epoch stamps the most recent member-add cut; member_epochs is
    # the per-cut [{at, roster}] history (per-member floors); epoch_roster is
    # the latest cut's roster (legacy/display).
    "member_epoch",
    "member_epochs",
    "epoch_roster",
    "google_disconnected",
    "onboarding_events",
    "onboarded_at",
    "onboarding_started_at",
    # Heartbeat identity-dedup: {gmail_message_id: iso_ts} of inbox items
    # already surfaced in a proactive alert (services/heartbeat.py).
    "hb_seen",
    # Saved address book: {lowercased name: {"phone": "+1...", "name": "..."}}
    # — lets "text my wife" resolve without the user re-typing numbers.
    "contacts",
    # Message-quota bookkeeping (services/usage.py):
    #   usage: {"period": "YYYY-MM", "count": int, "capped_notified": "YYYY-MM"}
    #   plan:  {"unlimited": bool, "limit": int}  (set when a user pays)
    "usage",
    "plan",
)


def _serialize(profile: HalUserProfile) -> dict:
    """Flatten a profile row (incl. extra_data onboarding fields) to a dict."""
    extra = profile.extra_data or {}
    return {
        "phone": profile.phone,
        "name": profile.name,
        "email": profile.email,
        "onboarded": profile.onboarded,
        "google_connected": profile.google_connected,
        "notes": profile.notes,
        "timezone": extra.get("timezone"),
        "home_location": extra.get("home_location"),
        "work_location": extra.get("work_location"),
        "google_offered": extra.get("google_offered", False),
        "google_disconnected": extra.get("google_disconnected", False),
        "asked_name": extra.get("asked_name", 0),
        "asked_timezone": extra.get("asked_timezone", 0),
        "asked_home": extra.get("asked_home", 0),
        "asked_work": extra.get("asked_work", 0),
        "onboarding_track": extra.get("onboarding_track"),
        "acquisition_source": extra.get("acquisition_source"),
        "asked_baby": extra.get("asked_baby", 0),
        "asked_city": extra.get("asked_city", 0),
        "member_epoch": extra.get("member_epoch"),
        "member_epochs": extra.get("member_epochs") or [],
        "epoch_roster": extra.get("epoch_roster") or [],
        "onboarding_events": extra.get("onboarding_events") or [],
        "onboarded_at": extra.get("onboarded_at"),
        "extra_data": extra,
    }


def _empty(phone: str) -> dict:
    """The synthetic profile for a silo with no row yet (a brand-new user)."""
    return {
        "phone": phone,
        "name": None,
        "email": None,
        "onboarded": False,
        "google_connected": False,
        "notes": None,
        "timezone": None,
        "home_location": None,
        "work_location": None,
        "google_offered": False,
        "google_disconnected": False,
        "asked_name": 0,
        "asked_timezone": 0,
        "asked_home": 0,
        "asked_work": 0,
        "onboarding_track": None,
        "acquisition_source": None,
        "asked_baby": 0,
        "asked_city": 0,
        "member_epoch": None,
        "member_epochs": [],
        "epoch_roster": [],
        "onboarding_events": [],
        "onboarded_at": None,
        "extra_data": {},
    }


async def get_profile(session: AsyncSession, phone: str) -> dict:
    """Get a user's profile, creating one if it doesn't exist."""
    stmt = select(HalUserProfile).where(HalUserProfile.phone == phone)
    result = await session.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        return _empty(phone)

    return _serialize(profile)


async def find_by_stripe(
    session: AsyncSession,
    *,
    customer_id: str | None = None,
    subscription_id: str | None = None,
) -> str | None:
    """Return the silo (phone) whose plan carries the given Stripe subscription or
    customer id, else None. Maps a subscription webhook (which has no
    client_reference_id) back to the user who paid."""
    plan = HalUserProfile.extra_data["plan"]
    conds = []
    if subscription_id:
        conds.append(plan["stripe_subscription_id"].astext == subscription_id)
    if customer_id:
        conds.append(plan["stripe_customer_id"].astext == customer_id)
    if not conds:
        return None
    stmt = select(HalUserProfile.phone).where(or_(*conds)).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_profile(session: AsyncSession, phone: str, **fields: object) -> dict:
    """Update a user's profile, creating one if it doesn't exist.

    Columns (name/email/onboarded/google_connected/notes) are set directly;
    the onboarding fields in EXTRA_KEYS are merged into the extra_data JSONB.
    """
    stmt = select(HalUserProfile).where(HalUserProfile.phone == phone)
    result = await session.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = HalUserProfile(phone=phone)
        session.add(profile)

    # Route the JSONB-backed keys into extra_data. Reassign the whole dict (not
    # in-place mutation) so SQLAlchemy marks the column dirty and persists it.
    extra_updates = {k: fields.pop(k) for k in list(fields) if k in EXTRA_KEYS}
    # Only store a valid IANA timezone — a bad string would make the onboarding
    # logic think tz is captured while resolve_tz silently falls back to default.
    tz = extra_updates.get("timezone")
    if tz is not None:
        try:
            ZoneInfo(str(tz))
        except Exception:
            log.warning("profiles.invalid_timezone", phone=phone, timezone=tz)
            extra_updates.pop("timezone", None)
    if extra_updates:
        merged = dict(profile.extra_data or {})
        merged.update(extra_updates)
        profile.extra_data = merged

    for key, value in fields.items():
        if hasattr(profile, key) and key not in ("id", "phone", "created_at", "updated_at"):
            setattr(profile, key, value)

    await session.flush()

    return _serialize(profile)
