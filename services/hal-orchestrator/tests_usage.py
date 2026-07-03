"""Tests for the per-user message quota (services/usage.py).

Uses an in-memory fake for get_profile/update_profile (monkeypatched into the
usage module) so the counting / reset / cap / plan logic is exercised without a
DB. Run: python3 services/hal-orchestrator/tests_usage.py
"""

import asyncio
import os
import sys
from types import SimpleNamespace

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hal_orchestrator.services.usage as usage
from hal_orchestrator.services.usage import (
    QuotaResult,
    enforce_quota,
    funding_message,
    is_metered,
    set_plan,
)

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        failures.append(name)


# --- In-memory profile store, monkeypatched into the usage module ---------- #
STORE: dict = {}


async def _fake_get_profile(session, silo):
    return {"phone": silo, "extra_data": dict(STORE.get(silo, {}))}


async def _fake_update_profile(session, silo, **fields):
    extra = dict(STORE.get(silo, {}))
    for k in ("usage", "plan"):
        if k in fields:
            extra[k] = fields[k]
    STORE[silo] = extra
    return {"phone": silo, "extra_data": extra}


usage.get_profile = _fake_get_profile
usage.update_profile = _fake_update_profile


def _settings(limit=3, payment_url="https://pay.hal/x", admin_phone="+15559999999"):
    return SimpleNamespace(
        free_message_limit=limit, payment_url=payment_url, admin_phone=admin_phone
    )


def run(coro):
    return asyncio.run(coro)


# --- is_metered ------------------------------------------------------------ #
print("is_metered:")
s = _settings()
check("1:1 real user is metered", is_metered("+15550001111", False, False, s))
check("group not metered", not is_metered("chatABC", True, False, s))
check("internal/heartbeat not metered", not is_metered("+15550001111", False, True, s))
check("admin not metered", not is_metered("+15559999999", False, False, s))
check(
    "cap disabled (limit 0) -> not metered",
    not is_metered("+15550001111", False, False, _settings(limit=0)),
)


# --- funding_message ------------------------------------------------------- #
print("funding_message:")
m = funding_message(_settings(), 3)
check("mentions limit + link + Apple Pay", "3 messages" in m and "pay.hal" in m and "Apple Pay" in m)
m2 = funding_message(_settings(payment_url=""), 3)
check("no link -> graceful coming-soon", "pay.hal" not in m2 and "reset" in m2.lower())


# --- enforce_quota: count, cap, reset -------------------------------------- #
print("enforce_quota — cap after N, then block:")
STORE.clear()
silo = "+15550002222"
s = _settings(limit=3)
r1 = run(enforce_quota(None, silo, s))
r2 = run(enforce_quota(None, silo, s))
r3 = run(enforce_quota(None, silo, s))
check("1st allowed (count 1)", r1.allowed and r1.count == 1)
check("3rd allowed (count 3)", r3.allowed and r3.count == 3)
r4 = run(enforce_quota(None, silo, s))
check("4th blocked", not r4.allowed and "messages this month" in r4.message)

print("enforce_quota — new calendar month resets the counter:")
STORE[silo] = {"usage": {"period": "2020-01", "count": 999}}
r = run(enforce_quota(None, silo, s))
check("stale-period count reset -> allowed at count 1", r.allowed and r.count == 1)

print("enforce_quota — paid plans bypass the cap:")
STORE[silo] = {"plan": {"unlimited": True}, "usage": {"period": "2020-01", "count": 999}}
r = run(enforce_quota(None, silo, s))
check("unlimited plan always allowed", r.allowed)

STORE[silo] = {"plan": {"unlimited": False, "limit": 100}}
# Simulate being at 50 in the current period.
import datetime as _dt

period = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m")
STORE[silo] = {"plan": {"unlimited": False, "limit": 100}, "usage": {"period": period, "count": 50}}
r = run(enforce_quota(None, silo, s))
check("plan limit override raises the cap", r.allowed and r.count == 51 and r.limit == 100)


# --- admin notify fires once per period ------------------------------------ #
print("admin notify on cap (once per period):")
import hal_orchestrator.state as state

# Drain any admin pings enqueued by earlier cap tests (the outbox is a shared
# global queue) so this sub-test counts only its own.
while not state.outbox.empty():
    state.outbox.get_nowait()

STORE.clear()
silo = "+15550003333"
s = _settings(limit=1)
run(enforce_quota(None, silo, s))          # count 1 (allowed)
run(enforce_quota(None, silo, s))          # blocked -> notify
run(enforce_quota(None, silo, s))          # blocked -> must NOT notify again
notes = []
while not state.outbox.empty():
    notes.append(state.outbox.get_nowait())
admin_pings = [n for n in notes if n.get("to") == s.admin_phone]
check("admin pinged exactly once", len(admin_pings) == 1, detail=f"got {len(admin_pings)}")


# --- set_plan unlocks + resets --------------------------------------------- #
print("set_plan:")
STORE.clear()
silo = "+15550004444"
STORE[silo] = {"usage": {"period": period, "count": 999}}
plan = run(set_plan(None, silo, unlimited=True))
check("set_plan unlimited", plan == {"unlimited": True})
check("set_plan reset the counter", STORE[silo]["usage"]["count"] == 0)
r = run(enforce_quota(None, silo, _settings(limit=3)))
check("granted user is unblocked", r.allowed)

plan2 = run(set_plan(None, silo, unlimited=False, limit=200))
check("set_plan with explicit limit", plan2 == {"unlimited": False, "limit": 200})


if failures:
    print(f"\n{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("\nAll usage/quota tests passed.")
