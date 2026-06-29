"""google_auth / google_calendar / google_gmail tools (per-silo, read-only).

Google is personal: a user connects their OWN account in their 1:1 chat. These
tools refuse in group silos — a shared group must never reach a member's email
or calendar, and a group should not own a Google account.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog

from hal_orchestrator.prompts.system import resolve_tz
from hal_orchestrator.services import google as gsvc
from hal_orchestrator.services.profiles import get_profile
from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

_GROUP_REFUSAL = (
    "Google (calendar/email) is personal and only works in a 1:1 chat with me — "
    "I won't touch anyone's account from a group. Tell the person to text me directly."
)
_NOT_CONFIGURED = (
    "Google isn't set up on this HAL instance yet (missing OAuth credentials)."
)


def _rfc3339(dt: datetime) -> str:
    return dt.isoformat()


async def tool_google_auth(args: dict, ctx: ToolContext) -> str:
    """status | start | disconnect — manage the user's Google connection."""
    if ctx.is_group:
        return _GROUP_REFUSAL
    if not gsvc.is_configured(ctx.settings):
        return _NOT_CONFIGURED

    action = args.get("action", "status")

    if action == "status":
        acct = await gsvc.get_account(ctx.session, ctx.phone)
        if acct and acct.access_token_enc:
            who = f" ({acct.google_email})" if acct.google_email else ""
            return f"Google is connected{who}. Read-only calendar + Gmail."
        return "Google is not connected. Use action=start to get a connect link."

    if action == "start":
        url = gsvc.build_auth_url(ctx.settings, ctx.phone)
        return (
            "Send the user EXACTLY this link on its own line and tell them to tap it, "
            "sign in, and approve read-only access, then text you back:\n"
            f"{url}\n"
            "(The link is good for 10 minutes and only connects THIS chat.)"
        )

    if action in ("disconnect", "revoke"):
        ok = await gsvc.disconnect(
            ctx.session, ctx.settings, ctx.http_client, ctx.phone
        )
        return (
            "Disconnected your Google account and revoked access."
            if ok
            else "There was no connected Google account."
        )

    return f"Unknown google_auth action: {action}. Use: status, start, disconnect."


async def _access_or_hint(ctx: ToolContext) -> tuple[str | None, str | None]:
    """Return (access_token, None) or (None, message_for_HAL)."""
    if ctx.is_group:
        return None, _GROUP_REFUSAL
    if not gsvc.is_configured(ctx.settings):
        return None, _NOT_CONFIGURED
    token = await gsvc.get_valid_access_token(
        ctx.session, ctx.settings, ctx.http_client, ctx.phone
    )
    if not token:
        return None, (
            "Google isn't connected (or access expired). Use google_auth action=start "
            "to send the user a connect link, then retry."
        )
    return token, None


async def tool_google_calendar(args: dict, ctx: ToolContext) -> str:
    """list_events | search_events — read-only Google Calendar."""
    token, hint = await _access_or_hint(ctx)
    if hint:
        return hint

    action = args.get("action", "list_events")
    # 1:1 only here (groups already refused above) — use the user's own tz so the
    # default calendar window is anchored to their local "now".
    profile = await get_profile(ctx.session, ctx.phone)
    now = datetime.now(resolve_tz(profile))

    if action in ("list_events", "search_events"):
        time_min = args.get("time_min") or _rfc3339(now)
        # Default window: through end of the 7th day out.
        default_max = (now + timedelta(days=7)).replace(
            hour=23, minute=59, second=59, microsecond=0
        )
        time_max = args.get("time_max") or _rfc3339(default_max)
        query = args.get("query") if action == "search_events" else args.get("query")
        try:
            max_results = int(args.get("max_results", 10))
        except (TypeError, ValueError):
            max_results = 10

        events = await gsvc.list_events(
            ctx.http_client, token, time_min, time_max, max_results, query
        )
        if events is None:
            return "Couldn't reach Google Calendar. Try again shortly."
        if not events:
            return "No events found in that window."
        lines = []
        for e in events:
            when = e["start"] or "?"
            loc = f" @ {e['location']}" if e.get("location") else ""
            lines.append(f"- {when}: {e['summary']}{loc}")
        return "Calendar events:\n" + "\n".join(lines)

    return f"Unknown google_calendar action: {action}. Use: list_events, search_events."


async def tool_google_gmail(args: dict, ctx: ToolContext) -> str:
    """list_emails | read_email — read-only Gmail."""
    token, hint = await _access_or_hint(ctx)
    if hint:
        return hint

    action = args.get("action", "list_emails")

    if action in ("list_emails", "search_emails"):
        query = args.get("query", "is:unread")
        try:
            max_results = int(args.get("max_results", 10))
        except (TypeError, ValueError):
            max_results = 10
        msgs = await gsvc.list_messages(ctx.http_client, token, query, max_results)
        if msgs is None:
            return "Couldn't reach Gmail. Try again shortly."
        if not msgs:
            return f"No emails match '{query}'."
        lines = []
        for m in msgs:
            lines.append(
                f"- [id: {m['id']}] from {m['from']} — {m['subject']}"
                + (f"  ({m['snippet'][:80]})" if m.get("snippet") else "")
            )
        return f"Emails matching '{query}':\n" + "\n".join(lines)

    if action == "read_email":
        mid = args.get("message_id") or args.get("id", "")
        if not mid:
            return "Error: message_id is required to read an email."
        msg = await gsvc.get_message(ctx.http_client, token, mid)
        if msg is None:
            return "Couldn't read that email (bad id or Gmail error)."
        return (
            f"From: {msg['from']}\nTo: {msg['to']}\nDate: {msg['date']}\n"
            f"Subject: {msg['subject']}\n\n{msg['body']}"
        )

    return f"Unknown google_gmail action: {action}. Use: list_emails, read_email."
