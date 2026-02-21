"""contacts tool — wraps services/profiles.py for user profile CRUD."""

from __future__ import annotations

import json

from hal_orchestrator.services.profiles import get_profile, update_profile
from hal_orchestrator.tools.registry import ToolContext


async def tool_contacts(args: dict, ctx: ToolContext) -> str:
    """Handle contacts actions: get, update."""
    action = args.get("action", "")

    if action == "get":
        profile = await get_profile(ctx.session, ctx.phone)
        return json.dumps(profile)

    elif action == "update":
        fields = {
            k: v
            for k, v in args.items()
            if k not in ("action",) and v is not None
        }
        if not fields:
            return "Error: no fields to update"
        profile = await update_profile(ctx.session, ctx.phone, **fields)
        return f"Profile updated: {json.dumps(profile)}"

    else:
        return f"Unknown contacts action: {action}. Use: get or update"
