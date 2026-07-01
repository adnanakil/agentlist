"""send_message tool — queues messages for the bridge to send."""

from __future__ import annotations

import re

import structlog

from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

# A handle the bridge can deliver to directly: a phone number (with/without
# +, spaces, dashes, parens) or an iMessage email address.
_PHONE_RX = re.compile(r"^\+?[\d\s().-]{7,}$")
_EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def _resolve_contact(ctx: ToolContext, to: str) -> tuple[str | None, str]:
    """Resolve a saved-contact name to a number. Returns (number|None, note).
    Never guesses: an unknown name returns the saved-contact list so the model
    asks the user instead of texting a stranger."""
    from hal_orchestrator.services.profiles import get_profile

    profile = await get_profile(ctx.session, ctx.phone)
    contacts = (profile.get("extra_data") or {}).get("contacts") or {}
    if not isinstance(contacts, dict):
        contacts = {}
    entry = contacts.get(to.strip().lower())
    if isinstance(entry, dict) and entry.get("phone"):
        return str(entry["phone"]), ""
    if isinstance(entry, str) and entry.strip():
        return entry, ""
    saved = ", ".join(sorted(contacts)) if contacts else "none saved yet"
    return None, (
        f"Error: '{to}' is not a phone number or a saved contact. Saved "
        f"contacts: {saved}. Ask the user for the number, then save it with "
        "contacts(action=add_contact, contact_name=..., contact_phone=...) so "
        "next time the name just works."
    )


async def tool_send_message(args: dict, ctx: ToolContext) -> str:
    """Queue an iMessage to be sent by the bridge.

    Instead of calling back to the bridge (which isn't publicly reachable),
    we accumulate side messages in the ToolContext. The message route returns
    them in the response so the bridge can send them.

    `to` may be a raw handle (phone/email) or the name of a saved contact
    (profile extra_data["contacts"]) — so "text my wife" works by name.
    """
    to = args.get("to", "")
    text = args.get("text", "")

    if not to or not text:
        return "Error: 'to' and 'text' are required"

    if not (_PHONE_RX.match(to.strip()) or _EMAIL_RX.match(to.strip())):
        resolved, note = await _resolve_contact(ctx, to)
        if not resolved:
            return note
        log.info("send_message.contact_resolved", name=to, to=resolved)
        to = resolved

    ctx.side_messages.append({"to": to, "text": text})
    log.info("send_message.queued", to=to, text=text[:50])
    return f"Message queued for {to}: {text}"
