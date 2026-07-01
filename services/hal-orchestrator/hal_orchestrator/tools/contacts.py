"""contacts tool — wraps services/profiles.py for user profile CRUD."""

from __future__ import annotations

import json

from hal_orchestrator.services.profiles import get_profile, update_profile
from hal_orchestrator.tools.registry import ToolContext


async def tool_contacts(args: dict, ctx: ToolContext) -> str:
    """Handle contacts actions: get, update, add_contact, list_contacts."""
    action = args.get("action", "")

    if action == "get":
        profile = await get_profile(ctx.session, ctx.phone)
        return json.dumps(profile)

    elif action == "update":
        fields = {
            k: v
            for k, v in args.items()
            if k not in ("action", "contact_name", "contact_phone") and v is not None
        }
        if not fields:
            return "Error: no fields to update"
        profile = await update_profile(ctx.session, ctx.phone, **fields)
        return f"Profile updated: {json.dumps(profile)}"

    elif action == "add_contact":
        name = (args.get("contact_name") or "").strip()
        phone = (args.get("contact_phone") or "").strip()
        if not name or not phone:
            return "Error: contact_name and contact_phone are required"
        profile = await get_profile(ctx.session, ctx.phone)
        contacts = dict((profile.get("extra_data") or {}).get("contacts") or {})
        contacts[name.lower()] = {"name": name, "phone": phone}
        await update_profile(ctx.session, ctx.phone, contacts=contacts)
        return (
            f"Contact saved: {name} -> {phone}. send_message now accepts "
            f"'{name}' as the recipient."
        )

    elif action == "list_contacts":
        profile = await get_profile(ctx.session, ctx.phone)
        contacts = (profile.get("extra_data") or {}).get("contacts") or {}
        if not contacts:
            return "No saved contacts yet."
        return "Saved contacts:\n" + "\n".join(
            f"- {v.get('name', k) if isinstance(v, dict) else k}: "
            f"{v.get('phone', v) if isinstance(v, dict) else v}"
            for k, v in sorted(contacts.items())
        )

    else:
        return (
            f"Unknown contacts action: {action}. "
            "Use: get, update, add_contact, or list_contacts"
        )
