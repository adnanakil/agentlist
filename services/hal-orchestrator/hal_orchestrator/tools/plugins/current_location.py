"""Ephemeral current location supplied by the user's Find My share."""

from __future__ import annotations

from datetime import datetime

from hal_orchestrator.tools.registry import ToolContext
from hal_orchestrator.tools.specs import ToolSpec, register_tool

_DECLARATION = {
    "name": "current_location",
    "description": (
        "Get the CURRENT SPEAKER'S live location from their explicit Find My "
        "share with HAL. Call this before handling 'near me', 'nearby', "
        "'closest', 'from here', 'where am I', or a travel request with no "
        "origin. The result exists only for this inbound turn. It cannot query "
        "another person, and an unavailable result must not be replaced with "
        "the user's saved home address."
    ),
    "parameters": {"type": "object", "properties": {}},
}


async def tool_current_location(_args: dict, ctx: ToolContext) -> str:
    location = ctx.current_location
    if not location:
        return (
            "Live location is unavailable for this turn. Do not assume the user is "
            "at home; ask them for their starting point or to share location with HAL."
        )

    label = str(location.get("label") or "").strip()
    if not label:
        return "Find My did not provide a usable location label for this turn."
    details = [f"Current speaker's Find My location: {label}."]
    updated = str(location.get("updated") or "").strip()
    if updated:
        details.append(f"Find My freshness: {updated}.")
    observed_at = location.get("observed_at")
    if isinstance(observed_at, datetime):
        details.append(f"HAL checked it at {observed_at.isoformat()}.")
    elif observed_at:
        details.append(f"HAL checked it at {observed_at}.")
    if location.get("approximate") is True:
        details.append("The shared location is approximate.")
    details.append(
        "Use it only to complete this request; do not repeat the precise address "
        "unless the user explicitly asked where they are."
    )
    return " ".join(details)


register_tool(
    ToolSpec(
        name="current_location",
        declaration=_DECLARATION,
        handler=(
            "hal_orchestrator.tools.plugins.current_location:tool_current_location"
        ),
        scopes=frozenset({"dm", "group"}),
        risk="read",
        parallel_safe=True,
    )
)
