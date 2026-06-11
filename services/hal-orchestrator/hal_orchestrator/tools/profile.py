"""profile tool — read/write the user's persistent profile (a markdown doc).

The profile lives in HalUserProfile.notes and is injected into the system prompt
on every turn (see prompts/system.py build_user_context), so anything saved here
is always in HAL's context — no recall needed. Use it for STABLE facts and
preferences (home base, gym, routines, family), not timestamped events (use
memory for those).
"""

from __future__ import annotations

from hal_orchestrator.services.profiles import get_profile, update_profile
from hal_orchestrator.tools.registry import ToolContext


async def tool_profile(args: dict, ctx: ToolContext) -> str:
    """Handle profile actions: view, set (replace), append."""
    action = args.get("action", "view")
    content = args.get("content", "")

    if action == "view":
        profile = await get_profile(ctx.session, ctx.phone)
        notes = (profile.get("notes") or "").strip()
        return f"Current profile:\n{notes}" if notes else "Profile is empty."

    if action in ("set", "update"):
        if not content:
            return "Error: content is required to save the profile"
        await update_profile(ctx.session, ctx.phone, notes=content)
        return "Profile saved."

    if action == "append":
        if not content:
            return "Error: content is required to append to the profile"
        profile = await get_profile(ctx.session, ctx.phone)
        existing = (profile.get("notes") or "").strip()
        new_notes = (existing + "\n" + content).strip() if existing else content
        await update_profile(ctx.session, ctx.phone, notes=new_notes)
        return "Profile updated."

    return f"Unknown profile action: {action}. Use: view, set, or append."
