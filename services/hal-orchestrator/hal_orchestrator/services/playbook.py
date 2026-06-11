"""Self-authored playbook — operating notes HAL writes for itself (GROWTH.md).

Active entries are injected into the system prompt for EVERY user, so this is
the global learning plane's highest-leverage output: a lesson learned at 3am
changes behavior at 7am with no deploy. Hard constraints:

- ADDITIVE GUIDANCE ONLY. Hard rules (privacy, no-booking, safety) live in
  code-owned prompt sections that the growth loop cannot touch.
- PRIVACY LINT. Every entry is checked against an all-silo PII denylist
  (names, emails) + phone/email regexes before publishing. Violations are
  rejected, never published.
- CAPPED. Bounded entry count/size so the prompt never silently bloats.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalPlaybookEntry

log = structlog.get_logger()

# Statuses whose entries are injected. "failing" stays live until the nightly
# synthesis revises or retires it — unproven, not necessarily harmful.
LIVE_STATUSES = ("active", "verified", "failing")

MAX_ENTRIES = 30
MAX_ENTRY_CHARS = 300
MAX_ADDS_PER_NIGHT = 3

_PHONE_RX = re.compile(r"\+?\d[\d\-\(\)\s]{7,}\d")
_EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# 5-minute prompt-block cache: one query per window, invalidated on publish.
_cache: dict = {"block": None, "at": 0.0}
_CACHE_TTL = 300.0


def lint_violation(text: str, denylist: list[str]) -> str | None:
    """Return the reason this text may NOT be published globally, or None."""
    if _PHONE_RX.search(text):
        return "contains a phone number"
    if _EMAIL_RX.search(text):
        return "contains an email"
    lower = text.lower()
    for name in denylist:
        if name and re.search(rf"\b{re.escape(name.lower())}\b", lower):
            return f"contains a known user name ({name})"
    return None


async def live_entries(session: AsyncSession) -> list[HalPlaybookEntry]:
    stmt = (
        select(HalPlaybookEntry)
        .where(HalPlaybookEntry.status.in_(LIVE_STATUSES))
        .order_by(HalPlaybookEntry.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_block(session: AsyncSession) -> str:
    """Prompt block of live entries ('' when empty). Cached briefly."""
    now = time.monotonic()
    if _cache["block"] is not None and now - _cache["at"] < _CACHE_TTL:
        return _cache["block"]
    entries = await live_entries(session)
    if not entries:
        block = ""
    else:
        lines = "\n".join(f"- {e.content}" for e in entries[:MAX_ENTRIES])
        block = (
            "\n\n## Operating Notes (lessons HAL learned from its own past "
            "failures — follow these)\n" + lines
        )
    _cache["block"] = block
    _cache["at"] = now
    return block


def invalidate_cache() -> None:
    _cache["block"] = None
    _cache["at"] = 0.0


async def apply_changes(
    session: AsyncSession,
    changes: dict,
    reflection_id,
    denylist: list[str],
) -> dict:
    """Apply a nightly synthesis's playbook changes through the lint + caps.
    changes = {add: [{content, hypothesis, target_category, target_detail}],
               revise: [{id, content?, hypothesis?}], retire: [ids]}.
    Returns a report of what happened (for the digest)."""
    added: list[str] = []
    revised: list[str] = []
    retired: list[str] = []
    rejected: list[str] = []

    entries = {str(e.id): e for e in await live_entries(session)}

    for entry_id in changes.get("retire") or []:
        e = entries.get(str(entry_id))
        if e is not None:
            e.status = "retired"
            e.updated_at = datetime.now(timezone.utc)
            retired.append(e.content[:60])

    for rev in changes.get("revise") or []:
        e = entries.get(str(rev.get("id", "")))
        if e is None:
            continue
        content = (rev.get("content") or e.content)[:MAX_ENTRY_CHARS]
        reason = lint_violation(content, denylist)
        if reason:
            rejected.append(f"revise {str(e.id)[:8]}: {reason}")
            continue
        e.content = content
        if rev.get("hypothesis"):
            e.hypothesis = rev["hypothesis"][:500]
        # A revised entry restarts verification.
        e.status = "active"
        e.clean_nights = 0
        e.fail_nights = 0
        e.updated_at = datetime.now(timezone.utc)
        revised.append(content[:60])

    live_count = sum(1 for e in entries.values() if e.status in LIVE_STATUSES)
    for add in (changes.get("add") or [])[:MAX_ADDS_PER_NIGHT]:
        content = (add.get("content") or "").strip()[:MAX_ENTRY_CHARS]
        if not content:
            continue
        reason = lint_violation(content, denylist)
        if reason:
            rejected.append(f"add: {reason}")
            continue
        if live_count >= MAX_ENTRIES:
            rejected.append("add: playbook at capacity (retire something first)")
            continue
        session.add(
            HalPlaybookEntry(
                content=content,
                hypothesis=(add.get("hypothesis") or "")[:500],
                target_category=(add.get("target_category") or None),
                target_detail=(add.get("target_detail") or "")[:200] or None,
                origin_reflection_id=reflection_id,
            )
        )
        live_count += 1
        added.append(content[:60])

    await session.flush()
    invalidate_cache()
    if rejected:
        log.warning("playbook.rejected", items=rejected)
    return {"added": added, "revised": revised, "retired": retired, "rejected": rejected}
