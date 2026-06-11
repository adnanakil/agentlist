"""Tests for the pure baby analytics in hal_orchestrator.services.baby,
using Bazzy's real June 9-11 schedule shape.

Run: python3 services/hal-orchestrator/tests_baby_analytics.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services.baby import (
    compute_patterns,
    detect_regression,
    forecast_next,
    pair_sleeps,
    summarize_day,
)

ET = ZoneInfo("America/New_York")


def et(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=ET).astimezone(timezone.utc)


# Bazzy's real logged pattern, June 9-11 2026 (from the live memories table).
EVENTS = [
    # June 9
    ("nap_start", et(2026, 6, 9, 8, 0)),
    ("wake", et(2026, 6, 9, 8, 46)),
    ("feed", et(2026, 6, 9, 10, 1)),
    ("nap_start", et(2026, 6, 9, 11, 5)),
    ("wake", et(2026, 6, 9, 11, 50)),
    ("feed", et(2026, 6, 9, 13, 30)),
    ("feed", et(2026, 6, 9, 18, 20)),
    ("bedtime", et(2026, 6, 9, 18, 45)),
    # June 10
    ("wake", et(2026, 6, 10, 6, 0)),
    ("feed", et(2026, 6, 10, 7, 20)),
    ("nap_start", et(2026, 6, 10, 7, 30)),
    ("wake", et(2026, 6, 10, 8, 35)),
    ("feed", et(2026, 6, 10, 9, 47)),
    ("nap_start", et(2026, 6, 10, 10, 38)),
    ("wake", et(2026, 6, 10, 12, 28)),
    ("feed", et(2026, 6, 10, 13, 23)),
    ("nap_start", et(2026, 6, 10, 14, 35)),
    ("wake", et(2026, 6, 10, 15, 40)),
    ("feed", et(2026, 6, 10, 18, 30)),
    ("bedtime", et(2026, 6, 10, 18, 45)),
    # June 11
    ("feed", et(2026, 6, 11, 5, 10)),
    ("wake", et(2026, 6, 11, 6, 20)),
    ("feed", et(2026, 6, 11, 7, 30)),
    ("nap_start", et(2026, 6, 11, 8, 0)),
    ("wake", et(2026, 6, 11, 8, 40)),
    ("feed", et(2026, 6, 11, 9, 50)),
    ("nap_start", et(2026, 6, 11, 11, 34)),
    ("wake", et(2026, 6, 11, 12, 14)),
    ("feed", et(2026, 6, 11, 12, 42)),
    ("nap_start", et(2026, 6, 11, 13, 54)),
]

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


print("pair_sleeps:")
sleeps = pair_sleeps(EVENTS)
closed_naps = [s for s in sleeps if not s.is_night and s.end is not None]
nights = [s for s in sleeps if s.is_night]
check("7 closed naps", len(closed_naps) == 7, f"got {len(closed_naps)}")
check("2 night sleeps", len(nights) == 2, f"got {len(nights)}")
# June 9 bedtime 6:45pm -> June 10 wake 6:00am = 675 min
check("night length 11h15m", nights[0].minutes == 675, f"got {nights[0].minutes}")
check("last sleep is open nap", sleeps[-1].end is None and not sleeps[-1].is_night)

print("summarize_day (June 10):")
s = summarize_day(EVENTS, ET, datetime(2026, 6, 10).date())
check("3 naps", len(s["naps"]) == 3, f"got {len(s['naps'])}")
check("4 feeds", len(s["feeds"]) == 4, f"got {len(s['feeds'])}")
check(
    "total nap minutes 65+110+65=240",
    s["total_nap_minutes"] == 240,
    f"got {s['total_nap_minutes']}",
)
check("morning wake 6:00", s["morning_wake"] == et(2026, 6, 10, 6, 0))
check("bedtime 6:45pm", s["bedtime"] == et(2026, 6, 10, 18, 45))
check("night 675m ended this morning", s["night_minutes"] == 675)

print("compute_patterns:")
now = et(2026, 6, 11, 14, 30)
p = compute_patterns(EVENTS, ET, now)
check("nap median 46-65m", 40 <= p["nap_minutes"] <= 66, f"got {p['nap_minutes']}")
check("feed interval ~2-3.5h", 120 <= p["feed_interval_minutes"] <= 210,
      f"got {p['feed_interval_minutes']}")
check("bedtime median 6:45pm = 1125", p["bedtime_minutes"] == 1125,
      f"got {p['bedtime_minutes']}")
check("naps per day ~3", p["naps_per_day"] == 3, f"got {p['naps_per_day']}")

print("forecast (currently napping at 2:30pm June 11):")
f = forecast_next(EVENTS, ET, now)
check("state napping", f["state"] == "napping", f"got {f['state']}")
check("expected wake exists", f["expected_wake"] is not None)
wake_local = f["expected_wake"].astimezone(ET)
check("expected wake ~2:30-3:30pm", 14 <= wake_local.hour <= 15, f"got {wake_local}")
feed_local = f["next_feed"].astimezone(ET)
check("next feed ~3-4pm", 15 <= feed_local.hour <= 16, f"got {feed_local}")
bed_local = f["expected_bedtime"].astimezone(ET)
check("bedtime ~6:45pm", bed_local.hour == 18 and bed_local.minute == 45, f"got {bed_local}")

print("forecast (awake after wake, evening):")
evening_events = EVENTS + [("wake", et(2026, 6, 11, 15, 30))]
f2 = forecast_next(evening_events, ET, et(2026, 6, 11, 17, 45))
check("state awake", f2["state"] == "awake")
check(
    "next sleep is bedtime not a nap (wake window crosses bedtime)",
    f2["next_nap"] is None,
    f"got next_nap={f2['next_nap']}",
)

print("forecast (night sleep -> tomorrow wake):")
night_events = evening_events + [("bedtime", et(2026, 6, 11, 18, 45))]
f3 = forecast_next(night_events, ET, et(2026, 6, 11, 20, 0))
check("state night", f3["state"] == "night")
w = f3["expected_wake"].astimezone(ET)
check("wake tomorrow ~6am", w.date() == datetime(2026, 6, 12).date() and 5 <= w.hour <= 7,
      f"got {w}")

print("detect_regression:")
# Healthy baseline: no flags on real data
flags = detect_regression(EVENTS, ET, now)
check("no false-positive flags", flags == [], f"got {flags}")
# Build a degraded recent period: baseline 7 days of good sleep, then 3 bad days
good, bad = [], []
base_day = datetime(2026, 6, 1, tzinfo=ET)
for i in range(7):
    d = base_day + timedelta(days=i)
    good += [
        ("nap_start", d.replace(hour=8).astimezone(timezone.utc)),
        ("wake", d.replace(hour=9, minute=30).astimezone(timezone.utc)),
        ("nap_start", d.replace(hour=12).astimezone(timezone.utc)),
        ("wake", d.replace(hour=14).astimezone(timezone.utc)),
        ("bedtime", d.replace(hour=19).astimezone(timezone.utc)),
        ("wake", (d + timedelta(days=1)).replace(hour=6).astimezone(timezone.utc)),
    ]
for i in range(7, 10):
    d = base_day + timedelta(days=i)
    bad += [
        ("nap_start", d.replace(hour=8).astimezone(timezone.utc)),
        ("wake", d.replace(hour=8, minute=30).astimezone(timezone.utc)),
        ("bedtime", d.replace(hour=19).astimezone(timezone.utc)),
        ("wake", d.replace(hour=23).astimezone(timezone.utc)),  # night wake
        ("nap_start", d.replace(hour=23, minute=30).astimezone(timezone.utc)),
        ("wake", (d + timedelta(days=1)).replace(hour=4).astimezone(timezone.utc)),
    ]
flags2 = detect_regression(good + bad, ET, datetime(2026, 6, 11, tzinfo=ET).astimezone(timezone.utc))
check("regression flagged on degraded data", len(flags2) >= 1, f"got {flags2}")
print(f"  flags: {flags2}")

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
