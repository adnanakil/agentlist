"""helpful_mode tool — turn the proactive daily brief on/off and tune it.

Writes per-user opt-in + preferences into profile.extra_data["helpful"], which
the helpful_loop (services/helpful.py) reads. Off until the user turns it on.
"""

from __future__ import annotations

from sqlalchemy import select

from ag_db.models import HalUserProfile
from hal_orchestrator.services.helpful import DEFAULT_INTERESTS
from hal_orchestrator.tools.registry import ToolContext

VALID_INTERESTS = {"weather", "events", "news", "agenda"}


async def _load(ctx: ToolContext) -> HalUserProfile | None:
    return (
        await ctx.session.execute(
            select(HalUserProfile).where(HalUserProfile.phone == ctx.phone)
        )
    ).scalar_one_or_none()


def _save(profile: HalUserProfile, hp: dict) -> None:
    merged = dict(profile.extra_data or {})
    merged["helpful"] = hp
    profile.extra_data = merged


def _summary(hp: dict) -> str:
    if not hp.get("enabled"):
        return "Helpful mode is OFF."
    return (
        f"Helpful mode is ON — daily brief ~{hp.get('hour', 8)}:00, "
        f"covering {', '.join(hp.get('interests') or DEFAULT_INTERESTS)}, "
        f"plus the occasional same-day heads-up."
    )


async def tool_helpful(args: dict, ctx: ToolContext) -> str:
    """Actions: on, off, status, set (interests=[...], hour=<0-23>)."""
    action = (args.get("action") or "status").strip().lower()
    profile = await _load(ctx)
    if profile is None:
        return "No profile here yet — say a bit about yourself first, then enable helpful mode."

    hp = dict((profile.extra_data or {}).get("helpful") or {})

    if action == "status":
        return _summary(hp)

    if action == "off":
        hp["enabled"] = False
        _save(profile, hp)
        await ctx.session.flush()
        return "Helpful mode is off — I won't send the daily brief or proactive pings."

    if action in ("on", "set"):
        if action == "on":
            hp["enabled"] = True
            hp.setdefault("interests", list(DEFAULT_INTERESTS))
            hp.setdefault("hour", 8)
        if "interests" in args:
            chosen = [i for i in (args.get("interests") or []) if i in VALID_INTERESTS]
            if chosen:
                hp["interests"] = chosen
        if "hour" in args:
            try:
                hp["hour"] = max(5, min(21, int(args["hour"])))
            except (TypeError, ValueError):
                return "Error: hour must be a number 5–21 (local)."
        if action == "set" and not hp.get("enabled"):
            return "Helpful mode is off — turn it on first (action=on)."
        _save(profile, hp)
        await ctx.session.flush()
        return ("Helpful mode on. " if action == "on" else "Updated. ") + _summary(hp)

    return "Unknown action. Use: on, off, status, set (interests, hour)."
