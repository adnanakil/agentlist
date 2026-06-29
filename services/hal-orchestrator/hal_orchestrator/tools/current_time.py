"""current_time tool — returns the current date and time in the USER'S local
timezone (with UTC for reference), so no model has to convert UTC→local.

Previously this returned UTC only and relied on the model to convert to the
user's timezone. Gemini/Sonnet did that silently; GLM did NOT — it parroted the
UTC time (e.g. texting "1:39 AM Saturday" when it was 9:39 PM Friday ET). Return
local time directly so any model gets it right.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hal_orchestrator.tools.registry import ToolContext


async def tool_current_time(ctx: ToolContext) -> str:
    """Current date + time in the silo's local timezone. The tz comes from the
    user's profile (resolve_tz), falling back to USER_TZ (America/New_York);
    groups use USER_TZ."""
    from hal_orchestrator.prompts.system import USER_TZ, resolve_tz

    tz = USER_TZ
    try:
        if not ctx.is_group:
            from hal_orchestrator.services.profiles import get_profile

            profile = await get_profile(ctx.session, ctx.phone)
            tz = resolve_tz(profile)
    except Exception:
        tz = USER_TZ

    now_local = datetime.now(tz)
    now_utc = datetime.now(timezone.utc)
    # Format: "Friday, June 26, 2026 at 9:39 PM EDT — your local time (01:39 UTC)"
    return (
        now_local.strftime("%A, %B %d, %Y at %-I:%M %p %Z")
        + " — your local time"
        + f" ({now_utc.strftime('%H:%M')} UTC)"
    )
