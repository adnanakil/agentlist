"""Tests for wake inference — an awake-implying event logged during an open
nap closes the nap (the 2026-07-23 "Ate 14:10 mid-nap, nap-cap nudge fired
anyway" incident).

Run: python3 services/hal-orchestrator/tests_baby_wake_inference.py
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ag_db.models import HalBabyEvent

from hal_orchestrator.services.baby import (
    AWAKE_KINDS,
    infer_wake_if_napping,
    pair_sleeps,
)

ET = ZoneInfo("America/New_York")

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


def et(h, mi):
    return datetime(2026, 7, 23, h, mi, tzinfo=ET).astimezone(timezone.utc)


class FakeFamily:
    id = "fam-1"


class FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class FakeSession:
    """execute() returns the canned "most recent sleep-relevant event";
    add() captures inserts."""

    def __init__(self, last_sleep_event):
        self._last = last_sleep_event
        self.added = []

    async def execute(self, stmt):
        return FakeResult(self._last)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


def prior(kind, at):
    return HalBabyEvent(family_id=FakeFamily.id, kind=kind, event_at=at, silo="s")


async def run_checks():
    print("infer_wake_if_napping:")

    # The incident: nap_start 12:37, feed logged for 2:10 — wake inferred.
    session = FakeSession(prior("nap_start", et(12, 37)))
    wake = await infer_wake_if_napping(
        session, FakeFamily(), "feed", et(14, 10), logged_by="+1", silo="s"
    )
    check("feed mid-nap infers wake", wake is not None)
    check("inferred wake at feed time", wake is not None and wake.event_at == et(14, 10))
    check("inferred wake persisted", len(session.added) == 1 and session.added[0].kind == "wake")
    check("note marks it inferred", wake is not None and "Inferred" in wake.note)

    # Dream feed during night sleep must NOT wake him (June-11 5:10am pattern).
    session = FakeSession(prior("bedtime", et(19, 0)))
    wake = await infer_wake_if_napping(
        session, FakeFamily(), "feed", et(22, 30), logged_by="+1", silo="s"
    )
    check("night dream feed does not infer wake", wake is None and not session.added)

    # Already awake — nothing to close.
    session = FakeSession(prior("wake", et(14, 0)))
    wake = await infer_wake_if_napping(
        session, FakeFamily(), "feed", et(14, 10), logged_by="+1", silo="s"
    )
    check("feed while awake infers nothing", wake is None and not session.added)

    # No sleep history at all.
    session = FakeSession(None)
    wake = await infer_wake_if_napping(
        session, FakeFamily(), "feed", et(14, 10), logged_by="+1", silo="s"
    )
    check("no history infers nothing", wake is None and not session.added)

    # Non-awake-implying kinds never trigger, even mid-nap.
    for kind in ("note", "wake", "nap_start", "bedtime"):
        session = FakeSession(prior("nap_start", et(12, 37)))
        wake = await infer_wake_if_napping(
            session, FakeFamily(), kind, et(14, 10), logged_by="+1", silo="s"
        )
        check(f"kind={kind} infers nothing", wake is None and not session.added)

    # All awake-implying kinds do.
    for kind in sorted(AWAKE_KINDS):
        session = FakeSession(prior("nap_start", et(12, 37)))
        wake = await infer_wake_if_napping(
            session, FakeFamily(), kind, et(14, 10), logged_by="+1", silo="s"
        )
        check(f"kind={kind} infers wake", wake is not None)

    print("pair_sleeps with inferred wake:")
    events = [
        ("nap_start", et(12, 37)),
        ("wake", et(14, 10)),  # what inference inserts
        ("feed", et(14, 10)),
    ]
    sleeps = pair_sleeps(events)
    check("nap closed", len(sleeps) == 1 and sleeps[0].end == et(14, 10))
    check("nap duration 93m", sleeps[0].minutes == 93)


asyncio.run(run_checks())

if failures:
    print(f"\n{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("\nall checks passed")
