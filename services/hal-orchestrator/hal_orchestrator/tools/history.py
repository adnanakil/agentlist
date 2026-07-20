"""recall_history tool — search past conversation by keyword + time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hal_orchestrator.prompts.system import USER_TZ
from hal_orchestrator.services.history_search import search_history
from hal_orchestrator.tools.registry import ToolContext


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    except ValueError:
        return None


# Refusal strings for the group= param — pulled out as constants so tests can
# check for them without duplicating the copy.
GROUP_TO_GROUP_REFUSAL = (
    "Group-to-group recall isn't available — you can only search this group's "
    "own history."
)
NOT_A_MEMBER_REFUSAL = "You can only recall groups you participate in."


async def tool_recall_history(args: dict, ctx: ToolContext) -> str:
    """Search the durable archive of THIS chat's past messages — or, when
    `group` is given, a group chat the caller is a member of (per the
    context catalog). A group search prepends that group's rolling summary
    and returns ONLY conversation content (summary + messages) — never the
    group's profile notes or per-member observations.

    MEMBERSHIP BOUNDARY: recall into a group's archive is floored at the
    group's membership epoch for anyone who wasn't in the room before it
    (services/membership.py). Longer-tenured members recall freely — that's
    the deliberate "catch them up" valve: their ask is the permission.

    Args: query (keywords), days_back (int), since/until (ISO), limit, group.
    """
    group = str(args.get("group") or "").strip()
    target_phone = ctx.phone
    prefix = ""
    floor = None
    floor_note = ""
    if group:
        if ctx.is_group:
            return GROUP_TO_GROUP_REFUSAL
        from hal_orchestrator.services.group_catalog import is_member

        if not await is_member(ctx.session, group, ctx.phone):
            return NOT_A_MEMBER_REFUSAL
        target_phone = group
        from hal_orchestrator.services.membership import recall_floor
        from hal_orchestrator.services.profiles import get_profile

        floor = recall_floor(await get_profile(ctx.session, group), ctx.phone)
        from hal_orchestrator.services.conversation import get_summary

        group_summary = (await get_summary(ctx.session, group)).strip()[:300]
        if group_summary:
            prefix = f"Group summary: {group_summary}\n\n"
    elif ctx.is_group:
        from hal_orchestrator.services.membership import recall_floor
        from hal_orchestrator.services.profiles import get_profile

        floor = recall_floor(
            await get_profile(ctx.session, ctx.phone), ctx.sender_phone
        )
    if floor is not None:
        floor_note = (
            "\n[Membership boundary: results are limited to messages since "
            "the newest member joined this thread — earlier history isn't "
            "shared with them. Don't present this as the full record.]"
        )

    query = args.get("query", "") or ""
    since = _parse_dt(args.get("since"))
    until = _parse_dt(args.get("until"))

    days_back = args.get("days_back")
    if since is None and days_back is not None:
        try:
            since = datetime.now(UTC) - timedelta(days=int(days_back))
        except (TypeError, ValueError):
            since = None

    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10

    if not query.strip() and since is None and until is None:
        return "Provide a query and/or a time range (days_back or since/until)."

    if floor is not None:
        since = floor if since is None else max(since, floor)

    rows = await search_history(ctx.session, target_phone, query, since, until, limit)
    if not rows:
        return prefix + "No matching past messages found." + floor_note

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
    return prefix + "Found in past conversation:\n" + "\n".join(lines) + floor_note
