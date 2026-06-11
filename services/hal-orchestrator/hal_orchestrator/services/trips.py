"""Trip coordination service — CRUD + date overlap logic."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalTrip

log = structlog.get_logger()

# Statuses
ACTIVE_STATUSES = {"collecting", "dates_locked", "searching", "voting"}


async def create_trip(
    session: AsyncSession,
    chat_id: str,
    location: str,
    created_by: str | None = None,
    group_name: str | None = None,
) -> dict:
    """Create a new trip. Cancels any existing active trip in the same chat."""
    # Cancel existing active trips for this chat
    stmt = (
        update(HalTrip)
        .where(HalTrip.chat_id == chat_id, HalTrip.status.in_(ACTIVE_STATUSES))
        .values(status="cancelled", updated_at=datetime.now(timezone.utc))
    )
    await session.execute(stmt)

    trip = HalTrip(
        chat_id=chat_id,
        location=location,
        status="collecting",
        created_by=created_by,
        group_name=group_name,
        participants={},
        options=[],
        votes={},
    )
    session.add(trip)
    await session.flush()

    log.info("trip.created", chat_id=chat_id, location=location)
    return {
        "id": str(trip.id),
        "location": location,
        "status": "collecting",
    }


async def get_active_trip(session: AsyncSession, chat_id: str) -> HalTrip | None:
    """Get the active trip for a chat, if any."""
    stmt = (
        select(HalTrip)
        .where(HalTrip.chat_id == chat_id, HalTrip.status.in_(ACTIVE_STATUSES))
        .order_by(HalTrip.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def add_availability(
    session: AsyncSession,
    chat_id: str,
    phone: str,
    name: str,
    available: list[dict],
    unavailable: list[str] | None = None,
) -> str:
    """Add or update a participant's availability.

    available: [{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}, ...]
    unavailable: ["YYYY-MM-DD", ...]
    """
    trip = await get_active_trip(session, chat_id)
    if not trip:
        return "No active trip in this chat."
    if trip.status != "collecting":
        return f"Trip dates are already locked. Status: {trip.status}"

    participants = dict(trip.participants)
    participants[phone] = {
        "name": name,
        "available": available,
        "unavailable": unavailable or [],
    }
    trip.participants = participants
    trip.updated_at = datetime.now(timezone.utc)
    await session.flush()

    log.info("trip.availability_added", chat_id=chat_id, phone=phone, name=name)
    return f"Got {name}'s availability."


def compute_overlap(participants: dict) -> list[dict]:
    """Compute overlapping date ranges across all participants.

    Returns list of {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} ranges.
    """
    if not participants:
        return []

    # Expand each participant's availability into a set of dates
    date_sets = []
    all_unavailable: set[date] = set()

    for phone, info in participants.items():
        person_dates: set[date] = set()
        for rng in info.get("available", []):
            try:
                start = date.fromisoformat(rng["start"])
                end = date.fromisoformat(rng["end"])
                d = start
                while d <= end:
                    person_dates.add(d)
                    d += timedelta(days=1)
            except (KeyError, ValueError):
                continue
        if person_dates:
            date_sets.append(person_dates)

        for d_str in info.get("unavailable", []):
            try:
                all_unavailable.add(date.fromisoformat(d_str))
            except ValueError:
                continue

    if not date_sets:
        return []

    # Intersect all sets
    overlap = date_sets[0]
    for ds in date_sets[1:]:
        overlap = overlap & ds

    # Remove unavailable dates
    overlap -= all_unavailable

    if not overlap:
        return []

    # Collapse into contiguous ranges
    sorted_dates = sorted(overlap)
    ranges = []
    range_start = sorted_dates[0]
    prev = sorted_dates[0]

    for d in sorted_dates[1:]:
        if d - prev > timedelta(days=1):
            ranges.append({"start": range_start.isoformat(), "end": prev.isoformat()})
            range_start = d
        prev = d
    ranges.append({"start": range_start.isoformat(), "end": prev.isoformat()})

    return ranges


async def get_trip_status(session: AsyncSession, chat_id: str) -> str:
    """Get a human-readable status for the active trip."""
    trip = await get_active_trip(session, chat_id)
    if not trip:
        return "No active trip in this chat."

    parts = [f"Trip to {trip.location} — status: {trip.status}"]

    participants = trip.participants or {}
    if participants:
        names = [info.get("name", phone) for phone, info in participants.items()]
        parts.append(f"Participants ({len(names)}): {', '.join(names)}")

    if trip.status == "collecting":
        overlap = compute_overlap(participants)
        if overlap:
            overlap_strs = [f"{r['start']} to {r['end']}" for r in overlap]
            parts.append(f"Overlapping dates: {'; '.join(overlap_strs)}")
        else:
            parts.append("No overlapping dates yet.")

    if trip.locked_dates:
        parts.append(
            f"Locked dates: {trip.locked_dates['start']} to {trip.locked_dates['end']}"
        )

    if trip.options:
        parts.append(f"Airbnb options: {len(trip.options)}")
        for i, opt in enumerate(trip.options, 1):
            parts.append(
                f"  {i}. {opt.get('title', 'Listing')} — "
                f"${opt.get('price_per_night', '?')}/night — "
                f"{opt.get('url', '')}"
            )

    if trip.votes:
        parts.append(f"Votes: {len(trip.votes)}/{len(participants)}")

    if trip.winner:
        parts.append(f"Winner: {trip.winner.get('title', 'Selected listing')}")

    return "\n".join(parts)


async def lock_dates(
    session: AsyncSession, chat_id: str, start: str, end: str
) -> str:
    """Lock the trip dates."""
    trip = await get_active_trip(session, chat_id)
    if not trip:
        return "No active trip in this chat."

    trip.locked_dates = {"start": start, "end": end}
    trip.status = "dates_locked"
    trip.updated_at = datetime.now(timezone.utc)
    await session.flush()

    log.info("trip.dates_locked", chat_id=chat_id, start=start, end=end)
    return f"Dates locked: {start} to {end}. Ready to search for Airbnbs."


async def add_options(
    session: AsyncSession, chat_id: str, options: list[dict]
) -> str:
    """Store Airbnb search results and move to voting."""
    trip = await get_active_trip(session, chat_id)
    if not trip:
        return "No active trip in this chat."

    trip.options = options
    trip.status = "voting"
    trip.updated_at = datetime.now(timezone.utc)
    await session.flush()

    log.info("trip.options_added", chat_id=chat_id, count=len(options))
    return f"Added {len(options)} options. Ready for voting."


async def cast_vote(
    session: AsyncSession, chat_id: str, phone: str, option_index: int
) -> str:
    """Cast a vote for an option (1-indexed)."""
    trip = await get_active_trip(session, chat_id)
    if not trip:
        return "No active trip in this chat."
    if trip.status != "voting":
        return f"Voting isn't open. Status: {trip.status}"
    if not trip.options:
        return "No options to vote on."
    if option_index < 1 or option_index > len(trip.options):
        return f"Invalid option. Choose 1-{len(trip.options)}."

    votes = dict(trip.votes)
    votes[phone] = option_index
    trip.votes = votes
    trip.updated_at = datetime.now(timezone.utc)
    await session.flush()

    participant_count = len(trip.participants)
    vote_count = len(votes)

    log.info("trip.vote", chat_id=chat_id, phone=phone, option=option_index)
    return f"Vote recorded ({vote_count}/{participant_count})."


async def tally_votes(session: AsyncSession, chat_id: str) -> str:
    """Tally votes and declare a winner."""
    trip = await get_active_trip(session, chat_id)
    if not trip:
        return "No active trip in this chat."
    if not trip.votes:
        return "No votes yet."

    # Count votes per option
    counts: dict[int, int] = {}
    for phone, option_idx in trip.votes.items():
        counts[option_idx] = counts.get(option_idx, 0) + 1

    winning_idx = max(counts, key=lambda k: counts[k])
    winning_option = trip.options[winning_idx - 1]  # 1-indexed

    trip.winner = winning_option
    trip.status = "booked"
    trip.updated_at = datetime.now(timezone.utc)
    await session.flush()

    log.info("trip.winner", chat_id=chat_id, option=winning_idx)
    return (
        f"Option {winning_idx} wins with {counts[winning_idx]} vote(s)!\n"
        f"{winning_option.get('title', 'Listing')} — "
        f"${winning_option.get('price_per_night', '?')}/night\n"
        f"{winning_option.get('url', '')}"
    )


async def cancel_trip(session: AsyncSession, chat_id: str) -> str:
    """Cancel the active trip."""
    trip = await get_active_trip(session, chat_id)
    if not trip:
        return "No active trip to cancel."

    trip.status = "cancelled"
    trip.updated_at = datetime.now(timezone.utc)
    await session.flush()

    log.info("trip.cancelled", chat_id=chat_id)
    return "Trip cancelled."


async def get_watched_chat_ids(session: AsyncSession) -> list[str]:
    """Chat_ids the bridge should forward in full: groups with an active trip
    PLUS ambiently-watched groups (trip-independent)."""
    from hal_orchestrator.services.watched import list_watched_chat_ids

    stmt = (
        select(HalTrip.chat_id)
        .where(HalTrip.status.in_(ACTIVE_STATUSES))
        .distinct()
    )
    result = await session.execute(stmt)
    trip_ids = [row[0] for row in result.fetchall()]
    watched_ids = await list_watched_chat_ids(session)
    return list(dict.fromkeys(trip_ids + watched_ids))
