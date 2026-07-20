"""forget-me — the C3 privacy promise, made real in code.

"Text 'forget me' and it's gone" is on the landing page and in the parent
playbook; this module is what makes that sentence TRUE. Full deletion of a
silo's data: profile, memories, conversation + archived history, turns,
reminders, skills, Google account rows, watches, cron jobs, trajectories,
friction events, follow-ups, inbound events, confirmations, group
observations about them, pending outbox messages to them — and the family
baby log WHEN they are its only keeper (a shared household log belongs to the
household; a co-parent leaving only removes their membership).

Deterministic, route-level, never model-mediated: the message route matches
the exact phrases and requires a confirm step ("forget me" → reply "delete
everything"). See routes/message.py.
"""

from __future__ import annotations

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import (
    HalActionConfirmation,
    HalBabyEvent,
    HalConversation,
    HalCronJob,
    HalFamily,
    HalFamilyMember,
    HalFollowup,
    HalFrictionEvent,
    HalGoogleAccount,
    HalGroupMember,
    HalGroupObservation,
    HalInboundEvent,
    HalMessage,
    HalOutboxMessage,
    HalReminder,
    HalSkillTrajectory,
    HalTurn,
    HalUserMemory,
    HalUserProfile,
    HalUserSkill,
    HalWatch,
)

log = structlog.get_logger()


async def forget_silo(session: AsyncSession, silo: str) -> dict[str, int]:
    """Delete EVERYTHING keyed to this silo. Returns {table: rows_deleted}
    for the receipt. The caller commits."""
    counts: dict[str, int] = {}

    async def wipe(label: str, stmt) -> None:
        result = await session.execute(stmt)
        if result.rowcount:
            counts[label] = counts.get(label, 0) + result.rowcount

    # Family log: sole keeper → the whole log goes; otherwise just their seat.
    fam_stmt = (
        select(HalFamily)
        .join(HalFamilyMember, HalFamilyMember.family_id == HalFamily.id)
        .where(HalFamilyMember.silo == silo)
    )
    family = (await session.execute(fam_stmt)).scalar_one_or_none()
    if family is not None:
        members = (
            await session.execute(
                select(HalFamilyMember).where(
                    HalFamilyMember.family_id == family.id
                )
            )
        ).scalars().all()
        others = [m for m in members if m.silo != silo]
        if others:
            await wipe(
                "family_membership",
                sa_delete(HalFamilyMember).where(HalFamilyMember.silo == silo),
            )
        else:
            await wipe(
                "baby_events",
                sa_delete(HalBabyEvent).where(
                    HalBabyEvent.family_id == family.id
                ),
            )
            await wipe(
                "family_membership",
                sa_delete(HalFamilyMember).where(
                    HalFamilyMember.family_id == family.id
                ),
            )
            await session.delete(family)
            counts["family"] = 1

    # Group traces: their membership rows, and their handle inside any group
    # epoch rosters (the entitlement lists) — a forgotten person leaves no
    # references behind. Other members' floors are unaffected.
    member_groups = set(
        (
            await session.execute(
                select(HalGroupMember.group_silo).where(
                    HalGroupMember.member_silo == silo
                )
            )
        ).scalars().all()
    )
    await wipe(
        "group_memberships",
        sa_delete(HalGroupMember).where(HalGroupMember.member_silo == silo),
    )
    if member_groups:
        from hal_orchestrator.services.profiles import get_profile, update_profile

        for group_silo in member_groups:
            gprof = await get_profile(session, group_silo)
            changed: dict = {}
            roster = gprof.get("epoch_roster") or []
            if silo in roster:
                changed["epoch_roster"] = [m for m in roster if m != silo]
            epochs = gprof.get("member_epochs") or []
            if any(silo in (e.get("roster") or []) for e in epochs):
                changed["member_epochs"] = [
                    {**e, "roster": [m for m in (e.get("roster") or []) if m != silo]}
                    for e in epochs
                ]
            if changed:
                await update_profile(session, group_silo, **changed)
                counts["epoch_rosters"] = counts.get("epoch_rosters", 0) + 1

    for label, model, col in (
        ("conversation", HalConversation, HalConversation.phone),
        ("memories", HalUserMemory, HalUserMemory.phone),
        ("reminders", HalReminder, HalReminder.phone),
        ("skills", HalUserSkill, HalUserSkill.phone),
        ("google_account", HalGoogleAccount, HalGoogleAccount.phone),
        ("archived_messages", HalMessage, HalMessage.phone),
        ("cron_jobs", HalCronJob, HalCronJob.phone),
        ("trajectories", HalSkillTrajectory, HalSkillTrajectory.phone),
        ("friction_events", HalFrictionEvent, HalFrictionEvent.phone),
        ("watches", HalWatch, HalWatch.phone),
        ("turns", HalTurn, HalTurn.phone),
        ("followups", HalFollowup, HalFollowup.silo),
        ("inbound_events", HalInboundEvent, HalInboundEvent.silo),
        ("confirmations", HalActionConfirmation, HalActionConfirmation.silo),
        ("group_observations", HalGroupObservation, HalGroupObservation.member_phone),
        ("outbox", HalOutboxMessage, HalOutboxMessage.destination),
    ):
        await wipe(label, sa_delete(model).where(col == silo))

    # Profile last — it holds the forget_pending marker until the end.
    await wipe(
        "profile", sa_delete(HalUserProfile).where(HalUserProfile.phone == silo)
    )

    await session.flush()
    log.info("forget.silo_deleted", silo=silo, counts=counts)
    return counts
