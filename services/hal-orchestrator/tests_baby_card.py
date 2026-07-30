"""Tests for the baby status/day cards (white + emoji design, 2026-07-20):

  1. _clock_past — the midnight-wrap rule (a 6:30 AM wake at 7:40 PM is
     TOMORROW, not "Soon"; a 2:30 AM feed at 11:50 PM is not "FEED DUE")
  2. render smoke — all three states produce a real PNG with the emoji path
  3. build_card_data shaping stays pure and total

Run:
    uv run python tests_baby_card.py
"""

import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services.baby_card import (
    _clock_past,
    render_card_png,
)

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


# --- 1. midnight-wrap clock logic ------------------------------------------- #
print("_clock_past:")
check("genuinely past (20 min ago)", _clock_past("3:20 PM", "3:00 PM") is True)
check("upcoming today", _clock_past("3:20 PM", "5:00 PM") is False)
check(
    "morning wake seen from evening = TOMORROW, not past",
    _clock_past("7:40 PM", "6:30 AM") is False,
)
check(
    "small-hours feed seen from 11:50 PM = tomorrow, not due",
    _clock_past("11:50 PM", "2:30 AM") is False,
)
check("same minute is not past", _clock_past("3:20 PM", "3:20 PM") is False)
check("overnight boundary: 11h59m ago is past", _clock_past("6:29 PM", "6:30 AM") is True)
check("None-safe", _clock_past(None, "3:00 PM") is False and _clock_past("3:00 PM", None) is False)
check("garbage-safe", _clock_past("nope", "3:00 PM") is False)

# --- 2. render smoke: three states, real PNGs, emoji drawn ------------------- #
print("\nrender smoke:")
base = {
    "baby": "Leo", "now": "10:18 AM", "last_feed": "8:55 AM",
    "next_feed": "11:50 AM", "expected_bedtime": "7:15 PM",
}
states = {
    "napping": {**base, "state": "napping", "asleep_since": "9:42 AM",
                "expected_wake": "10:32 AM", "next_nap": None, "last_nap_end": None},
    "awake": {**base, "state": "awake", "asleep_since": None,
              "expected_wake": None, "next_nap": "12:05 PM", "last_nap_end": "10:02 AM"},
    "night": {**base, "state": "night", "now": "7:40 PM", "asleep_since": "7:15 PM",
              "expected_wake": "6:30 AM", "next_nap": None, "last_nap_end": None},
}
for name, data in states.items():
    png = render_card_png(data)
    check(f"{name} renders a PNG", png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 5000)

# Night card must show the morning wake time, not "Soon" (the wrap bug).
import io

from PIL import Image

night_png = render_card_png(states["night"])
img = Image.open(io.BytesIO(night_png))
# The SOFT focal block sits at y≈302..418; "Soon" is ~4 chars wide (~110px),
# "6:30 AM" is ~180px. Measure ink width inside the block as a proxy.
block = img.crop((92, 350, 560, 396)).convert("L")
ink_cols = [x for x in range(block.width) if min(block.getpixel((x, y)) for y in range(0, block.height, 4)) < 120]
ink_width = (max(ink_cols) - min(ink_cols)) if ink_cols else 0
check("night card shows a wake TIME, not 'Soon'", ink_width > 150, f"ink width {ink_width}px")

# Missing-value totality: renderer never crashes on sparse data.
sparse = {"baby": "Leo", "now": "10:18 AM", "state": "awake"}
png = render_card_png(sparse)
check("sparse data still renders", png[:8] == b"\x89PNG\r\n\x1a\n")

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all passed")

# --- example card (setup-time preview) -------------------------------------- #
print("\nexample card:")
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from hal_orchestrator.services.baby_card import (
    build_example_card_data,
    render_example_card,
)

now = datetime(2026, 7, 30, 14, 0, tzinfo=UTC)
ex = build_example_card_data("Theo", ZoneInfo("America/New_York"), now)
check("example is flagged", ex.get("_example") is True)
check("example shows a napping state", ex["state"] == "napping")
check("example times derive from now", ex["now"] == "10:00 AM" and ex["asleep_since"] == "9:35 AM")
check("example has feed + wake + bedtime", all(ex[k] for k in ("last_feed", "next_feed", "expected_wake", "expected_bedtime")))
png = render_example_card("Theo", ZoneInfo("America/New_York"), now)
check("example renders a PNG", png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 5000)
real = render_card_png({**ex, "_example": False})
check("example badge changes the pixels", png != real)

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all passed (incl. example card)")
