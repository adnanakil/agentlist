"""Tests for guided onboarding: per-user timezone resolution, the step-aware
onboarding block, and the profile extra_data routing (tz/location in JSONB).

Run: python3 services/hal-orchestrator/tests_onboarding.py
"""

import asyncio
import os
import sys
from zoneinfo import ZoneInfo

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.prompts.system import (
    USER_TZ,
    _now_block,
    _onboarding_block,
    is_onboarding_complete,
    resolve_tz,
)
from hal_orchestrator.services.profiles import _empty, get_profile, update_profile

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


print("resolve_tz:")
check("valid IANA", resolve_tz({"timezone": "America/Los_Angeles"}).key == "America/Los_Angeles")
check("garbage -> default", resolve_tz({"timezone": "Mars/Phobos"}) is USER_TZ)
check("None -> default", resolve_tz(None) is USER_TZ)
check("no key -> default", resolve_tz({}) is USER_TZ)

print("_now_block:")
check("reflects passed tz", "America/Los_Angeles" in _now_block(ZoneInfo("America/Los_Angeles")))
check("default is ET", "America/New_York" in _now_block())

print("_onboarding_block:")
check("onboarded -> None", _onboarding_block({"onboarded": True, "name": "A"}) is None)
check("no profile -> None", _onboarding_block(None) is None)

base = _empty("+15550001111")

b0 = _onboarding_block(base)
check("step1 first contact + asks name", b0 and "FIRST contact" in b0 and "name" in b0.lower())

b1 = _onboarding_block({**base, "name": "Sarah"})
check("step2 asks timezone", b1 and "timezone" in b1.lower())
check("step2 lists captured name", b1 and "name=Sarah" in b1)
check("step2 doesn't re-ask name", b1 and "ask their name" not in b1)

b2 = _onboarding_block({**base, "name": "Sarah", "timezone": "America/Los_Angeles"})
check("step3 asks where they live", b2 and "live" in b2.lower())
check("step3 lists tz captured", b2 and "timezone=America/Los_Angeles" in b2)

b3 = _onboarding_block(
    {**base, "name": "S", "timezone": "America/Los_Angeles", "home_location": "LA"}
)
check("step4 asks work", b3 and "work" in b3.lower())

b4 = _onboarding_block(
    {
        **base,
        "name": "S",
        "timezone": "America/Los_Angeles",
        "home_location": "LA",
        "work_location": "DTLA",
    }
)
check("step5 offers google", b4 and "google_auth" in b4 and "optional" in b4.lower())

complete = {
    "name": "S",
    "timezone": "America/Los_Angeles",
    "home_location": "LA",
    "work_location": "DTLA",
}
b5 = _onboarding_block({**base, **complete, "google_offered": True})
check("step6 completes after offer", b5 and "onboarded=true" in b5)
b5b = _onboarding_block({**base, **complete, "google_connected": True})
check("step6 completes after connect", b5b and "onboarded=true" in b5b)

print("is_onboarding_complete:")
check("empty -> incomplete", not is_onboarding_complete(None))
check("name only -> incomplete", not is_onboarding_complete({**base, "name": "Sarah"}))
check(
    "missing google offer/connect -> incomplete",
    not is_onboarding_complete({**base, **complete}),
)
check(
    "complete after google offered",
    is_onboarding_complete({**base, **complete, "google_offered": True}),
)
check(
    "complete after google connected",
    is_onboarding_complete({**base, **complete, "google_connected": True}),
)


# --- profiles.py extra_data routing (fake session, no DB) ------------------- #
class FakeProfile:
    def __init__(self, phone):
        self.id = None
        self.phone = phone
        self.name = None
        self.email = None
        self.onboarded = False
        self.google_connected = False
        self.notes = None
        self.extra_data = {}
        self.created_at = None
        self.updated_at = None


class FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class FakeSession:
    def __init__(self, obj):
        self._obj = obj
        self.added = []

    async def execute(self, stmt):
        return FakeResult(self._obj)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


async def run_db_checks():
    print("update_profile / get_profile routing:")
    prof = FakeProfile("+15550001111")
    out = await update_profile(
        FakeSession(prof),
        "+15550001111",
        name="Sarah",
        timezone="America/Los_Angeles",
        home_location="Park Slope",
        google_offered=True,
    )
    check("name set as column", prof.name == "Sarah")
    check("tz routed to extra_data", prof.extra_data.get("timezone") == "America/Los_Angeles")
    check("home routed to extra_data", prof.extra_data.get("home_location") == "Park Slope")
    check("google_offered routed", prof.extra_data.get("google_offered") is True)
    check("name not in extra_data", "name" not in prof.extra_data)
    check("serialize surfaces tz", out["timezone"] == "America/Los_Angeles")
    check("serialize surfaces home", out["home_location"] == "Park Slope")

    # invalid timezone is dropped, never stored
    prof2 = FakeProfile("+1")
    await update_profile(FakeSession(prof2), "+1", timezone="Pacific Time")
    check("invalid tz dropped", "timezone" not in prof2.extra_data)

    # extra_data is reassigned to a NEW dict (SQLAlchemy JSONB dirty-tracking)
    prof3 = FakeProfile("+x")
    orig = prof3.extra_data
    await update_profile(FakeSession(prof3), "+x", work_location="Office")
    check("extra_data reassigned (new dict)", prof3.extra_data is not orig)

    # get_profile: serialize an existing row, _empty for a missing one
    g = await get_profile(FakeSession(prof), "+15550001111")
    check("get_profile serializes extra fields", g["home_location"] == "Park Slope")
    e = await get_profile(FakeSession(None), "+nope")
    check(
        "get_profile empty for missing row",
        e["onboarded"] is False and e["timezone"] is None and e["google_offered"] is False,
    )


asyncio.run(run_db_checks())

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all passed")
