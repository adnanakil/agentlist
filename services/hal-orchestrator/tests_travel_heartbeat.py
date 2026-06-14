"""Tests for the travel_time tool's pure logic and the heartbeat scheduler.

Run: python3 services/hal-orchestrator/tests_travel_heartbeat.py
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ag_common.config import HalOrchestratorConfig
from hal_orchestrator.tools.travel_time import (
    _fmt_duration,
    _seconds,
    format_route,
    tool_travel_time,
)
from hal_orchestrator.services.heartbeat import due_silos, in_active_hours

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


print("travel_time parsing/formatting:")
check("seconds parse", _seconds("6720s") == 6720)
check("seconds garbage", _seconds(None) is None and _seconds("abc") is None)
check("duration min", _fmt_duration(540) == "9 min")
check("duration hr+min", _fmt_duration(6720) == "1 hr 52 min")
check("duration exact hr", _fmt_duration(7200) == "2 hr")

drive = {"duration": "6720s", "staticDuration": "6300s", "distanceMeters": 137000}
out = format_route(drive, "drive", "Chelsea", "Mattituck")
check("drive duration shown", "1 hr 52 min" in out, out)
check("drive traffic delta", "1 hr 45 min typical" in out and "slower" in out, out)
check("drive miles", "85.1 mi" in out, out)

calm = {"duration": "6360s", "staticDuration": "6300s", "distanceMeters": 137000}
out = format_route(calm, "drive", "A", "B")
check("small delta -> normal traffic", "normal traffic" in out, out)

transit = {
    "duration": "8100s",
    "distanceMeters": 130000,
    "legs": [
        {
            "steps": [
                {"noTransit": True},
                {
                    "transitDetails": {
                        "transitLine": {"nameShort": "LIRR Ronkonkoma"},
                        "stopDetails": {
                            "departureStop": {"name": "Penn Station"},
                            "departureTime": "2026-06-12T20:19:00Z",
                            "arrivalStop": {"name": "Ronkonkoma"},
                            "arrivalTime": "2026-06-12T21:35:00Z",
                        },
                    }
                },
            ]
        }
    ],
}
out = format_route(transit, "transit", "Chelsea", "Mattituck")
check("transit line named", "LIRR Ronkonkoma" in out, out)
check("transit stops + local times", "Penn Station 4:19 PM" in out, out)

check(
    "no route", "No route found" in format_route({}, "drive", "A", "B")
)

print("travel_time arg validation (no network):")


class _Ctx:
    def __init__(self, key):
        self.settings = HalOrchestratorConfig(google_maps_api_key=key)
        self.http_client = None


out = asyncio.run(tool_travel_time({"origin": "A", "destination": "B"}, _Ctx("")))
check("missing key -> clear error", "not configured" in out, out)
out = asyncio.run(tool_travel_time({"origin": "", "destination": "B"}, _Ctx("k")))
check("missing origin", "origin and destination" in out, out)
out = asyncio.run(tool_travel_time({"origin": "A", "destination": "B", "mode": "teleport"}, _Ctx("k")))
check("bad mode", "mode must be" in out, out)
out = asyncio.run(
    tool_travel_time(
        {"origin": "A", "destination": "B", "mode": "drive", "arrival_time": "2099-01-01T00:00:00+00:00"},
        _Ctx("k"),
    )
)
check("arrival_time drive rejected", "only supported for transit" in out, out)
out = asyncio.run(
    tool_travel_time({"origin": "A", "destination": "B", "departure_time": "tomorrow"}, _Ctx("k"))
)
check("bad iso rejected", "invalid departure_time" in out, out)

print("heartbeat scheduling:")
cfg = HalOrchestratorConfig()
check("7am active", in_active_hours(datetime(2026, 6, 12, 7, 0), cfg))
check("9pm active", in_active_hours(datetime(2026, 6, 12, 21, 59), cfg))
check("10pm quiet", not in_active_hours(datetime(2026, 6, 12, 22, 0), cfg))
check("3am quiet", not in_active_hours(datetime(2026, 6, 12, 3, 0), cfg))

now = datetime.now(timezone.utc)
last = {"+1a": now - timedelta(minutes=20), "+1b": now - timedelta(minutes=5)}
due = due_silos(["+1a", "+1b", "+1c"], last, now, cfg)
check("overdue + never-run due", due == ["+1a", "+1c"], due)
check("recent not due", "+1b" not in due)
many = [f"+1{i}" for i in range(30)]
check("tick cap", len(due_silos(many, {}, now, cfg)) == cfg.heartbeat_max_silos_per_tick)

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all passed")
