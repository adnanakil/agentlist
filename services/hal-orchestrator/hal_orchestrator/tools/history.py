"""recall_history tool — search past conversation by keyword + time."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hal_orchestrator.prompts.system import USER_TZ
from hal_orchestrator.services.history_search import search_history
from hal_orchestrator.tools.registry import ToolContext


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError:
        return None


async def tool_recall_history(args: dict, ctx: ToolContext) -> str:
    """Search the durable archive of THIS chat's past messages.

    Args: query (keywords), days_back (int), since/until (ISO), limit.
    """
    query = args.get("query", "") or ""
    since = _parse_dt(args.get("since"))
    until = _parse_dt(args.get("until"))

    days_back = args.get("days_back")
    if since is None and days_back is not None:
        try:
            since = datetime.now(timezone.utc) - timedelta(days=int(days_back))
        except (TypeError, ValueError):
            since = None

    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10

    if not query.strip() and since is None and until is None:
        return "Provide a query and/or a time range (days_back or since/until)."

    rows = await search_history(ctx.session, ctx.phone, query, since, until, limit)
    if not rows:
        return "No matching past messages found."

    lines = []
    for r in rows:
        when = r["at"]
        try:
            when = (
                datetime.fromisoformat(r["at"])
                .astimezone(USER_TZ)
                .strftime("%a %b %-d, %-I:%M %p")
            )
        except (ValueError, TypeError):
            pass
        who = "You" if r["role"] == "assistant" else "User"
        lines.append(f"[{when}] {who}: {r['content'][:240]}")
    return "Found in past conversation:\n" + "\n".join(lines)
