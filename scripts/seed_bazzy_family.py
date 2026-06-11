"""One-off seed: Bazzy family + backfill events from legacy memory lines.

Creates the family linking Adnan's DM, Joyce's DM, and the family group chat;
sets standing preferences (auto wind-down/bottle-prep reminders, 2h nap cap,
tummy-time routine from Adnan's existing rule); backfills hal_baby_events by
parsing the free-text "Bazzy fed 9:47am" / "Bazzy started eating at ..." lines
out of hal_user_memories; and schedules the daily 7:15pm ET /baby-digest cron
to the group chat.

Idempotent: skips any piece that already exists.

Usage:
  DATABASE_URL=postgresql+asyncpg://... python scripts/seed_bazzy_family.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "ag-db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "ag-common"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ag_db.models import (
    HalBabyEvent,
    HalCronJob,
    HalFamily,
    HalFamilyMember,
    HalUserMemory,
)

ET = ZoneInfo("America/New_York")

ADNAN = "+12017570419"
JOYCE = "+16508239042"
GROUP = "chat783794800760957500"

SETTINGS = {
    "auto_reminders": True,
    "auto_wind_down": True,
    "auto_feed_prep": True,
    "nap_cap_minutes": 120,
    "routines": [
        {"after": "feed", "offset_min": 30, "text": "Tummy time for Bazzy"},
    ],
}

DIGEST_PROMPT = "/baby-digest"
DIGEST_LOCAL_TIME = time(19, 15)  # 7:15 PM ET

# --------------------------------------------------------------------------- #
# Legacy memory-line parsing
# --------------------------------------------------------------------------- #

MONTHS = {
    m: i + 1
    for i, m in enumerate(
        "January February March April May June July August "
        "September October November December".split()
    )
}

RE_DATE = re.compile(r"on (\w+) (\d{1,2}), (\d{4})")
RE_SHORT = re.compile(
    r"Bazzy (fed|woke|nap START|sleep START)\s+(\d{1,2}):(\d{2})\s*(am|pm)", re.I
)
RE_FEED = re.compile(r"Bazzy (?:started eating|ate) at (\d{1,2}):(\d{2})\s*(AM|PM)", re.I)
RE_SLEEP = re.compile(
    r"Bazzy (?:fell asleep|went to sleep)\S*?(?:\s+(?:in the stroller|for his \w+ nap))?"
    r" at (\d{1,2}):(\d{2})\s*(AM|PM)",
    re.I,
)
RE_WAKE = re.compile(
    r"Bazzy woke up(?: from his(?: \w+)? nap)? at (\d{1,2}):(\d{2})\s*(AM|PM)", re.I
)
RE_RANGE = re.compile(
    r"Bazzy slept from (\d{1,2}):(\d{2})\s*(AM|PM) to (\d{1,2}):(\d{2})\s*(AM|PM)", re.I
)

SHORT_KIND = {
    "fed": "feed",
    "woke": "wake",
    "nap start": "nap_start",
    "sleep start": "bedtime",
}


def _to_utc(d, hour12: int, minute: int, ampm: str) -> datetime:
    h = hour12 % 12 + (12 if ampm.lower() == "pm" else 0)
    return datetime(d.year, d.month, d.day, h, minute, tzinfo=ET).astimezone(
        timezone.utc
    )


def _sleep_kind(at_utc: datetime) -> str:
    return "bedtime" if at_utc.astimezone(ET).hour >= 18 else "nap_start"


def parse_memory(content: str, created_at: datetime) -> list[tuple[str, datetime]]:
    """Extract (kind, utc datetime) events from one legacy memory line."""
    m = RE_DATE.search(content)
    if m and m.group(1) in MONTHS:
        base = datetime(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2))).date()
    else:
        base = created_at.astimezone(ET).date()

    events: list[tuple[str, datetime]] = []

    for m in RE_SHORT.finditer(content):
        at = _to_utc(base, int(m.group(2)), int(m.group(3)), m.group(4))
        events.append((SHORT_KIND[m.group(1).lower()], at))
    if events:
        return events

    for m in RE_RANGE.finditer(content):
        start = _to_utc(base, int(m.group(1)), int(m.group(2)), m.group(3))
        end = _to_utc(base, int(m.group(4)), int(m.group(5)), m.group(6))
        events += [("nap_start", start), ("wake", end)]
    for m in RE_FEED.finditer(content):
        events.append(("feed", _to_utc(base, int(m.group(1)), int(m.group(2)), m.group(3))))
    for m in RE_SLEEP.finditer(content):
        at = _to_utc(base, int(m.group(1)), int(m.group(2)), m.group(3))
        events.append((_sleep_kind(at), at))
    for m in RE_WAKE.finditer(content):
        events.append(("wake", _to_utc(base, int(m.group(1)), int(m.group(2)), m.group(3))))
    return events


def dedupe(events: list[tuple[str, datetime, str]]) -> list[tuple[str, datetime, str]]:
    """Drop same-kind events within 10 minutes of an earlier one."""
    out: list[tuple[str, datetime, str]] = []
    for kind, at, silo in sorted(events, key=lambda e: e[1]):
        if any(
            k == kind and abs((at - a).total_seconds()) <= 600 for k, a, _ in out
        ):
            continue
        out.append((kind, at, silo))
    return out


# --------------------------------------------------------------------------- #
# Seed
# --------------------------------------------------------------------------- #


async def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL")
    engine = create_async_engine(url)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async with sessionmaker() as session:
        # 1. Family + members
        family = (
            await session.execute(
                select(HalFamily).where(HalFamily.baby_name == "Bazzy")
            )
        ).scalar_one_or_none()
        if family is None:
            family = HalFamily(
                name="Akil family",
                baby_name="Bazzy",
                timezone="America/New_York",
                settings=SETTINGS,
                state={},
            )
            session.add(family)
            await session.flush()
            print(f"created family {family.id}")
        else:
            print(f"family exists: {family.id}")

        for silo, role in ((ADNAN, "parent"), (JOYCE, "parent"), (GROUP, "group")):
            existing = (
                await session.execute(
                    select(HalFamilyMember).where(HalFamilyMember.silo == silo)
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(HalFamilyMember(family_id=family.id, silo=silo, role=role))
                print(f"added member {silo} ({role})")
        await session.flush()

        # 2. Backfill events from legacy memory lines
        count = (
            await session.execute(
                select(HalBabyEvent).where(HalBabyEvent.family_id == family.id).limit(1)
            )
        ).scalar_one_or_none()
        if count is not None:
            print("events already backfilled, skipping")
        else:
            memories = (
                (
                    await session.execute(
                        select(HalUserMemory)
                        .where(HalUserMemory.phone.in_([ADNAN, JOYCE, GROUP]))
                        .order_by(HalUserMemory.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )
            raw: list[tuple[str, datetime, str]] = []
            for mem in memories:
                for kind, at in parse_memory(mem.content, mem.created_at):
                    raw.append((kind, at, mem.phone))
            events = dedupe(raw)
            for kind, at, silo in events:
                session.add(
                    HalBabyEvent(
                        family_id=family.id,
                        kind=kind,
                        event_at=at,
                        logged_by=None,
                        silo=silo,
                        note="backfilled from memory log",
                    )
                )
            await session.flush()
            print(f"backfilled {len(events)} events ({len(raw) - len(events)} dupes dropped)")
            for kind, at, silo in events:
                print(f"  {at.astimezone(ET).strftime('%b %-d %-I:%M %p')}  {kind}")

        # 3. Evening digest cron (daily 7:15pm ET to the group)
        existing_job = (
            await session.execute(
                select(HalCronJob).where(
                    HalCronJob.phone == GROUP,
                    HalCronJob.prompt == DIGEST_PROMPT,
                    HalCronJob.active == True,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if existing_job is None:
            now_et = datetime.now(ET)
            run_local = datetime.combine(now_et.date(), DIGEST_LOCAL_TIME, tzinfo=ET)
            if run_local <= now_et:
                run_local += timedelta(days=1)
            session.add(
                HalCronJob(
                    phone=GROUP,
                    prompt=DIGEST_PROMPT,
                    recurrence="daily",
                    next_run_at=run_local.astimezone(timezone.utc),
                    is_group=True,
                    chat_id=GROUP,
                    sender_phone=ADNAN,
                )
            )
            print(f"scheduled daily digest, first run {run_local}")
        else:
            print("digest cron already exists")

        await session.commit()
    await engine.dispose()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
