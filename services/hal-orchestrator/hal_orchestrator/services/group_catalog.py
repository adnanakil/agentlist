"""Group-context catalog — a controlled window from a group chat into a
member's own 1:1 with HAL.

Direction of flow (enforced here and at the call sites, mirroring
group_observations.py's one-way valve):
  WRITE: record_participation() is called on every group turn where we know
         the sender — the only provable "membership" signal we have (we can't
         enumerate an iMessage chat's roster, so "spoke there" is the proxy
         for "is in it").
  READ:  build_catalog() is called only when assembling a 1:1 turn's context;
         is_member() gates the recall_history(group=...) pull. Group turns
         never call either read path, so a group can't see another group.

The catalog itself is deliberately tiny (~900 chars capped) — just enough for
the model to recognize "oh, this is the trip they planned in the family
group" and decide to pull the real thread with recall_history(group=<id>).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalConversation, HalGroupMember
from hal_orchestrator.services.identity import normalize_handle

log = structlog.get_logger()

MAX_GROUPS = 5
WINDOW_DAYS = 14
RECENT_WINDOW_HOURS = 6  # a group active this recently earns a longer head
SHORT_HEAD_CHARS = 150
LONG_HEAD_CHARS = 400
MAX_BLOCK_CHARS = 900

CATALOG_HEADER = "## Group chats you're in (context catalog)"
CATALOG_INSTRUCTION = (
    "(To read any of these threads: recall_history with group=<id>. Only "
    "reference group content when relevant.)"
)


async def record_participation(
    session: AsyncSession,
    group_silo: str,
    member_silo: str,
    group_name: str | None = None,
    now: datetime | None = None,
) -> None:
    """Upsert one (group, member) row, proving membership and refreshing
    last_spoke_at. group_name is updated only when a non-empty value is
    given — a later message shouldn't blank out a name we already have.

    Atomic ON CONFLICT upsert (not select-then-insert): a lost race would
    raise IntegrityError mid-turn and poison the caller's session — this can
    never conflict. Timestamps are order-independent (GREATEST/LEAST), so the
    backfill replaying OLD history after live rows exist can't regress
    last_spoke_at backwards (or push first_seen forward)."""
    member_silo = normalize_handle(member_silo)
    if not group_silo or not member_silo:
        return
    now = now or datetime.now(timezone.utc)
    from sqlalchemy import func
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from ag_db.models import new_uuid

    stmt = pg_insert(HalGroupMember).values(
        id=new_uuid(),
        group_silo=group_silo,
        member_silo=member_silo,
        group_name=group_name or None,
        first_seen=now,
        last_spoke_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_hal_group_members_group_member",
        set_={
            "last_spoke_at": func.greatest(
                HalGroupMember.last_spoke_at, stmt.excluded.last_spoke_at
            ),
            "first_seen": func.least(
                HalGroupMember.first_seen, stmt.excluded.first_seen
            ),
            "group_name": func.coalesce(
                stmt.excluded.group_name, HalGroupMember.group_name
            ),
        },
    )
    await session.execute(stmt)


async def is_member(session: AsyncSession, group_silo: str, member_silo: str) -> bool:
    """True if `member_silo` has ever spoken in `group_silo` (our only proof
    of membership). Gates recall_history(group=...)."""
    member_silo = normalize_handle(member_silo)
    if not group_silo or not member_silo:
        return False
    stmt = select(HalGroupMember.id).where(
        HalGroupMember.group_silo == group_silo,
        HalGroupMember.member_silo == member_silo,
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def load_catalog_rows(
    session: AsyncSession,
    member_silo: str,
    now: datetime,
    max_groups: int = MAX_GROUPS,
    window_days: int = WINDOW_DAYS,
) -> list[dict]:
    """Groups this member is in, newest-activity first, capped. 'Activity' is
    the group's own conversation.updated_at (its most recent real turn) when
    a conversation row exists, else the member's last_spoke_at — a fallback
    for a freshly-backfilled group with no live conversation yet. Groups with
    no activity inside `window_days` are dropped entirely (stale groups
    shouldn't clutter every 1:1 turn's context)."""
    member_silo = normalize_handle(member_silo)
    if not member_silo:
        return []
    cutoff = now - timedelta(days=window_days)
    stmt = (
        select(
            HalGroupMember.group_silo,
            HalGroupMember.group_name,
            HalGroupMember.last_spoke_at,
            HalConversation.summary,
            HalConversation.updated_at,
        )
        .outerjoin(HalConversation, HalConversation.phone == HalGroupMember.group_silo)
        .where(HalGroupMember.member_silo == member_silo)
    )
    rows = (await session.execute(stmt)).all()

    out: list[dict] = []
    for group_silo, group_name, last_spoke_at, summary, updated_at in rows:
        activity = updated_at or last_spoke_at
        if activity is None or activity < cutoff:
            continue
        out.append(
            {
                "group_silo": group_silo,
                "group_name": group_name,
                "activity": activity,
                "summary": summary or "",
            }
        )
    out.sort(key=lambda r: r["activity"], reverse=True)
    return out[:max_groups]


def _short_label(group_silo: str) -> str:
    """A group with no saved name falls back to a shortened chat id — the
    raw id is long and not meaningful to read in a prompt."""
    if len(group_silo) <= 16:
        return group_silo
    return group_silo[:12] + "…"


def _relative_time(activity: datetime, now: datetime) -> str:
    delta = (now - activity).total_seconds()
    minutes = max(delta, 0) / 60
    if minutes < 60:
        return f"{max(1, round(minutes))}m ago"
    hours = minutes / 60
    if hours < 24:
        return f"{round(hours)}h ago"
    return f"{round(hours / 24)}d ago"


def format_catalog(rows: list[dict], now: datetime) -> str | None:
    """Render the catalog block from `rows` (as returned by
    load_catalog_rows). PURE — no DB access — so it's unit-testable on its
    own. Returns None when there's nothing to show."""
    if not rows:
        return None

    lines = [CATALOG_HEADER]
    # Budget the per-group lines against the total cap, minus the header and
    # the trailing instruction line (both always included).
    budget = MAX_BLOCK_CHARS - len(CATALOG_HEADER) - len(CATALOG_INSTRUCTION) - 2
    for row in rows:
        activity = row.get("activity")
        name = row.get("group_name") or _short_label(row.get("group_silo", ""))
        gid = row.get("group_silo", "")
        rel = _relative_time(activity, now) if activity else "unknown"
        recent = activity is not None and (now - activity) <= timedelta(
            hours=RECENT_WINDOW_HOURS
        )
        head_len = LONG_HEAD_CHARS if recent else SHORT_HEAD_CHARS
        # Strip newlines inside the summary head — this is one line per group.
        head = " ".join((row.get("summary") or "").split())[:head_len]
        line = f'- "{name}" (id: {gid}) — active {rel}: {head}'
        if len(line) > budget:
            break
        lines.append(line)
        budget -= len(line)
    lines.append(CATALOG_INSTRUCTION)
    return "\n".join(lines)


async def build_catalog(
    session: AsyncSession, member_silo: str, now: datetime | None = None
) -> str | None:
    """Load + format this member's group catalog. Best-effort: any failure
    is logged and swallowed — a broken catalog must never break a 1:1 turn."""
    now = now or datetime.now(timezone.utc)
    try:
        rows = await load_catalog_rows(session, member_silo, now)
        return format_catalog(rows, now)
    except Exception:
        log.exception("group_catalog.build_failed", member=member_silo)
        return None
