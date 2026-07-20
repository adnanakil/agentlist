"""Membership epochs — the group knowledge boundary.

iMessage never shows a newly added member the messages from before they
joined, and neither does HAL: **in a group, HAL speaks only from what the
whole current room has seen.** When a member is added to a known group, the
thread's working knowledge CUTS at that moment (an "epoch"):

- the working conversation + rolling summary are cleared (the raw history
  stays in the durable archive),
- archive recall is floored at the epoch for anyone who wasn't in the room
  before it — while longer-tenured members keep full recall, which is the
  explicit, human-normal valve ("HAL, catch Dave up"): someone entitled to
  the context chooses to re-share it,
- ambient auto-recall (the prompt injection nobody asked for) is floored at
  the epoch for EVERYONE, so pre-epoch content can only re-enter the room
  through a member's deliberate ask.

Structured shared-by-design state — the family baby log (HalFamily) — is
deliberately NOT cut: a caregiver joining the family thread is *supposed*
to see the log. Free text never crosses a membership boundary
automatically; only typed structures do.

State lives on the group silo's profile (extra_data):
  member_epoch  : ISO timestamp of the most recent membership cut (the
                  ambient floor)
  member_epochs : [{at, roster}] — one entry per cut, oldest first; roster
                  is who had SPOKEN in the room before THAT cut. Floors are
                  PER MEMBER: each requester is floored at the epoch where
                  they themselves entered — a member who joined at cut N
                  never gains pre-N recall just because a later cut happened
                  (the union-roster leak found in adversarial review).
  epoch_roster  : the latest cut's roster (legacy/back-compat display)

Known tradeoff (documented, not a bug): rosters are spoke-only — iMessage
rosters can't be enumerated, so a member who never spoke before a cut is
floored like a newcomer. The catch-up valve covers them.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalGroupMember

log = structlog.get_logger()


MAX_EPOCHS = 20


async def cut_membership_epoch(session: AsyncSession, group_silo: str) -> None:
    """Record a membership epoch for a group: append {at, roster-who-spoke-
    before-this-cut} to the epoch history and clear the working conversation
    + rolling summary. Idempotent-ish: a second cut moments later appends a
    near-identical epoch (harmless — per-member floors resolve identically)."""
    from hal_orchestrator.services.conversation import clear_conversation
    from hal_orchestrator.services.profiles import get_profile, update_profile

    now_iso = datetime.now(UTC).isoformat()

    members = (
        await session.execute(
            select(HalGroupMember.member_silo).where(
                HalGroupMember.group_silo == group_silo
            )
        )
    ).scalars().all()
    roster = sorted(set(members))

    profile = await get_profile(session, group_silo)
    epochs = list(profile.get("member_epochs") or [])
    if not epochs and profile.get("member_epoch"):
        # Legacy single-epoch shape → seed the history from it.
        epochs = [
            {
                "at": profile["member_epoch"],
                "roster": profile.get("epoch_roster") or [],
            }
        ]
    epochs.append({"at": now_iso, "roster": roster})
    epochs = epochs[-MAX_EPOCHS:]

    await update_profile(
        session, group_silo,
        member_epoch=now_iso,
        member_epochs=epochs,
        epoch_roster=roster,
    )
    await clear_conversation(session, group_silo)
    log.info(
        "membership.epoch_cut",
        silo=group_silo,
        epochs=len(epochs),
        roster_size=len(roster),
    )


def _parse_at(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def recall_floor(profile: dict | None, requester: str | None) -> datetime | None:
    """The archive floor for `requester` in a group, from the group's profile
    dict. None = unrestricted. PER-MEMBER: the floor is the epoch at which
    the requester themselves entered the room —
      - in the FIRST epoch's roster → None (pre-dates every cut)
      - first appears in epoch i's roster → they entered at cut i-1: floored
        there, forever (a later cut never widens their view)
      - in no roster, or requester=None (AMBIENT context — the room's shared
        prompt) → floored at the LATEST epoch. PURE."""
    if not profile:
        return None
    epochs = list(profile.get("member_epochs") or [])
    if not epochs:
        if not profile.get("member_epoch"):
            return None
        epochs = [
            {
                "at": profile["member_epoch"],
                "roster": profile.get("epoch_roster") or [],
            }
        ]
    if requester:
        for i, ep in enumerate(epochs):
            if requester in (ep.get("roster") or []):
                if i == 0:
                    return None
                return _parse_at(epochs[i - 1].get("at")) or _parse_at(
                    epochs[-1].get("at")
                )
    return _parse_at(epochs[-1].get("at"))


async def group_memory_floor(
    session: AsyncSession, silo: str, requester: str | None
) -> datetime | None:
    """Convenience: the recall floor for a GROUP silo's free-text stores
    (memories, archive), loaded from its profile. None for 1:1 silos."""
    from hal_orchestrator.services.identity import is_group_id

    if not is_group_id(silo):
        return None
    from hal_orchestrator.services.profiles import get_profile

    return recall_floor(await get_profile(session, silo), requester)
