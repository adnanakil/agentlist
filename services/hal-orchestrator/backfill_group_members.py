"""Backfill hal_group_members from existing message history.

The group-context catalog (hal_orchestrator/services/group_catalog.py) needs
proof that a member has spoken in a group before it'll show that group in
their 1:1 catalog. Going forward that proof is recorded live (message.py
calls record_participation() on every group turn), but groups that were
already active before this feature shipped have no rows yet — this script
mines the durable message archive (hal_messages) for the sender-prefix
convention group history already uses ("[+12017570419]: hi", same regex as
group_observations.extract_participants) and upserts one row per (group,
sender) with their last-seen timestamp.

STRICTLY read-only on hal_messages/hal_conversations; the only table it
writes is hal_group_members, and only with --apply (default is dry-run —
prints what it would do and exits without touching the database).

Usage:
  python3 backfill_group_members.py [--database-url URL] [--apply]
Env: DATABASE_URL used when --database-url is omitted.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Same convention as group_observations.PARTICIPANT_RX: sender prefixes as
# they appear in stored group message content, e.g. "[+12017570419]: hi".
PARTICIPANT_RX = re.compile(r"\[(\+\d{7,15})\]")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Postgres URL (defaults to $DATABASE_URL)",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually write rows. Without this, only prints what would happen.",
    )
    return p.parse_args()


async def _find_group_silos(session, is_group_id) -> list[str]:
    """Group silos from both hal_conversations.phone and distinct
    hal_messages.phone — a group could have one without the other (e.g. a
    conversation row that's since been cleared)."""
    from ag_db.models import HalConversation, HalMessage
    from sqlalchemy import select

    convo_phones = (await session.execute(select(HalConversation.phone))).scalars().all()
    msg_phones = (
        (await session.execute(select(HalMessage.phone).distinct())).scalars().all()
    )
    return sorted({p for p in [*convo_phones, *msg_phones] if is_group_id(p)})


async def _sender_last_spoke(session, group_silo: str, normalize_handle) -> dict[str, datetime]:
    """{normalized sender handle: latest created_at} mined from this group's
    archived user-role messages."""
    from ag_db.models import HalMessage
    from sqlalchemy import select

    rows = (
        await session.execute(
            select(HalMessage.content, HalMessage.created_at).where(
                HalMessage.phone == group_silo, HalMessage.role == "user"
            )
        )
    ).all()
    latest: dict[str, datetime] = {}
    for content, created_at in rows:
        for raw_handle in PARTICIPANT_RX.findall(content or ""):
            handle = normalize_handle(raw_handle)
            if not handle:
                continue
            if handle not in latest or created_at > latest[handle]:
                latest[handle] = created_at
    return latest


async def main() -> None:
    args = parse_args()
    if not args.database_url:
        print("Need --database-url or DATABASE_URL env", file=sys.stderr)
        sys.exit(1)

    from ag_db.session import create_engine_and_session
    from hal_orchestrator.services.group_catalog import record_participation
    from hal_orchestrator.services.identity import is_group_id, normalize_handle

    engine, Session = create_engine_and_session(args.database_url)
    total_rows = 0
    try:
        async with Session() as session:
            group_silos = await _find_group_silos(session, is_group_id)
            print(f"found {len(group_silos)} group silo(s)")

            for group_silo in group_silos:
                latest = await _sender_last_spoke(session, group_silo, normalize_handle)
                if not latest:
                    continue
                print(f"{group_silo}: {len(latest)} sender(s)")
                for handle, last_at in sorted(latest.items()):
                    print(f"  {handle}  last spoke {last_at.isoformat()}")
                    total_rows += 1
                    if args.apply:
                        # Backfill has no separate "first seen" signal, so the
                        # last-spoke timestamp doubles as both first_seen and
                        # last_spoke_at for a freshly-created row (matches
                        # record_participation's own insert behavior).
                        await record_participation(session, group_silo, handle, now=last_at)

            if args.apply:
                await session.commit()
                print(f"applied: upserted {total_rows} row(s)")
            else:
                print(f"dry-run: would upsert {total_rows} row(s) — pass --apply to write")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
