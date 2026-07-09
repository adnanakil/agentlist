"""parking tool — find (and, soon, pay) NYC parking / camera tickets by plate.

`action=lookup` (default): pull every OPEN violation for a plate from NYC's
live dataset — summons number, what it was for, amount due, and a view-ticket
link — plus the total owed and the official pay URL.

Paying is being built in phases (see FEATURE_PLAN / architecture): today the
tool hands over the exact summons + pay link so the user taps to pay; the
auto-pay phase (stateful browser session + confirmation screenshot) will drive
the CityPay flow to one tap from done. `action=pay` returns that hand-off now.
"""

from __future__ import annotations

import structlog

from hal_orchestrator.prompts.system import resolve_tz
from hal_orchestrator.services import parking as p
from hal_orchestrator.services.profiles import get_profile
from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()


async def tool_parking(args: dict, ctx: ToolContext) -> str:
    action = (args.get("action") or "lookup").strip().lower()
    plate = (args.get("plate") or "").strip()
    state = (args.get("state") or "NY").strip().upper() or "NY"

    if not plate:
        return (
            "Error: a license plate is required (plate=..., and state=... if the "
            "plate isn't a NY plate)."
        )

    profile = await get_profile(ctx.session, ctx.phone) if not ctx.is_group else None
    tz = resolve_tz(profile)

    try:
        violations = await p.lookup_violations(ctx.http_client, plate, state)
    except Exception as exc:
        log.warning("parking.lookup_failed", error=str(exc), plate=plate[:12])
        return (
            "Couldn't reach NYC's violations database just now — try again in a "
            "moment. (It's an official city data source and is usually up.)"
        )

    if action == "lookup":
        return p.format_violations(violations, tz, plate, state)

    if action == "pay":
        if not violations:
            return p.format_violations(violations, tz, plate, state)
        summons = (args.get("summons_number") or "").strip()
        target = None
        if summons:
            target = next(
                (v for v in violations if str(v.get("summons_number")) == summons),
                None,
            )
            if target is None:
                return (
                    f"No open violation with summons #{summons} on {state} plate "
                    f"{p.normalize_plate(plate)}. Current open ones:\n\n"
                    + p.format_violations(violations, tz, plate, state)
                )
        # Hand-off (tap-to-pay) until autonomous submission ships. Present the
        # exact summons + pay link; don't claim to have paid anything.
        chosen = [target] if target else violations
        due = p.total_due(chosen)
        listing = "\n".join(
            p.format_violation(v, tz, index=i) for i, v in enumerate(chosen, 1)
        )
        return (
            f"[HAL can't submit the payment autonomously yet — that's the next "
            f"phase. For now hand the user this so they pay in ~2 taps.]\n\n"
            f"Ready to pay (${due:,.2f}):\n\n{listing}\n\n"
            f"Pay here: {p.PAY_URL} — enter the summons number above."
        )

    return f"Unknown parking action: {action}. Use: lookup, pay."
