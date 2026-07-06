"""Tests for the 2026-07-05 group-restraint + follow-up hardening pass.

Covers the deterministic pieces: tact-gate prompt content, reminder supersede
matching, follow-up event keys / phase windows / scan parsing, and the
follow-up prompts' silence escape. The model-judgment halves (tact verdicts,
scan quality, draft tone) are exercised live, not here.

Run: python3 services/hal-orchestrator/tests_group_hardening.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


# --------------------------------------------------------------------------- #
print("tact gate prompt — hardened DROP rules:")
from hal_orchestrator.routes.message import build_tact_prompt  # noqa: E402

p = build_tact_prompt("A: hi", "Adnan", "They're checking us in lol", "Actually no check-in is needed")
check("on-the-ground rule present", "on-the-ground" in p.lower() or "own on-the-ground" in p.lower())
check("butt-out rule present", "butt out" in p.lower())
check("stfu listed as stay-out signal", "stfu" in p.lower())
check("no summary block when none given", "What HAL knows about this group" not in p)
p2 = build_tact_prompt("A: hi", "Adnan", "msg", "draft", summary="Users prefer the assistant to step back.")
check("summary block included when given", "What HAL knows about this group" in p2)
check("summary text reaches the gate", "step back" in p2)

# --------------------------------------------------------------------------- #
print("reminder supersede — is_probable_duplicate:")
from hal_orchestrator.services.reminders import is_probable_duplicate  # noqa: E402

a = "Hey Seth! What day this week works for lunch with Adnan? Somewhere near Pier 57"
b = "Hey Seth! Time to lock in a day for lunch with Adnan next week. What day works for you?"
check("re-negotiated ping detected as duplicate", is_probable_duplicate(a, b))
check("unrelated reminders NOT duplicates",
      not is_probable_duplicate("Call the dentist about the crown", "Pick up the dry cleaning downtown"))
check("empty text never duplicate", not is_probable_duplicate("", "call mom"))

# --------------------------------------------------------------------------- #
print("followup — event_key:")
from hal_orchestrator.services.followup import (  # noqa: E402
    build_checkin_prompt,
    build_suggest_prompt,
    event_key,
    parse_scan_reply,
    pick_phase,
)

t0 = datetime(2026, 6, 30, 17, 30, tzinfo=timezone.utc)
k1 = event_key("Adnan and Seth had lunch at Market 57 (Pier 57)", t0)
check("key starts with the date", k1.startswith("2026-06-30:"))
check("same summary → stable key",
      k1 == event_key("Adnan and Seth had lunch at Market 57 (Pier 57)", t0))
check("different day → different key",
      k1 != event_key("Adnan and Seth had lunch at Market 57 (Pier 57)", t0 + timedelta(days=1)))

print("followup — same_event fuzzy dedup:")
from hal_orchestrator.services.followup import same_event  # noqa: E402

check("reworded rescan matches",
      same_event("Adnan and Seth had lunch at Market 57 (Pier 57)",
                 "Lunch at Market 57 for Seth and Adnan"))
check("different events don't match",
      not same_event("Lunch with Seth at Market 57",
                     "Bronx Zoo trip with Bazzy and Joyce"))

print("supersede — min_shared guard (review finding):")
check("2-shared-word short reminders NOT auto-dup",
      not is_probable_duplicate("call dentist about the crown",
                                "pick up crown from dentist office"))
check("Seth pair still detected with min_shared",
      is_probable_duplicate(a, b))

print("enforcer — honest-correction negation matcher:")
from hal_orchestrator.routes.message import _looks_like_honest_correction  # noqa: E402

for t in ["I couldn't log it — was that a bottle or nursing?",
          "I wasn't able to set the reminder, what time did you mean?",
          "Nothing was logged yet — nap or feed?",
          "I haven't texted him yet — what's his number?"]:
    check(f"negated: {t[:40]!r}", _looks_like_honest_correction(t))
for t in ["Logged ✅ wake at 7:15", "Reminder set for 9 AM", "Texted him just now"]:
    check(f"claim not negated: {t[:35]!r}", not _looks_like_honest_correction(t))

# --------------------------------------------------------------------------- #
print("followup — pick_phase windows:")
now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
check("mid-event (1h ago) → None",
      pick_phase(now - timedelta(hours=1), now, False, False) is None)
check("5h after → checkin",
      pick_phase(now - timedelta(hours=5), now, False, False) == "checkin")
check("5h after, already checked in → None",
      pick_phase(now - timedelta(hours=5), now, True, False) is None)
check("3 days after, checked in → suggest",
      pick_phase(now - timedelta(days=3), now, True, False) == "suggest")
check("3 days after, never checked in → suggest (too late for checkin)",
      pick_phase(now - timedelta(days=3), now, False, False) == "suggest")
check("both phases done → None",
      pick_phase(now - timedelta(days=3), now, True, True) is None)
check("10 days after → None (event too old)",
      pick_phase(now - timedelta(days=10), now, True, False) is None)

# --------------------------------------------------------------------------- #
print("followup — parse_scan_reply:")
good = '{"events": [{"summary": "Lunch at Market 57", "ended_at": "2026-06-30T17:30:00+00:00", "followed_up": false}]}'
evs = parse_scan_reply(good)
check("valid JSON parsed", len(evs) == 1 and evs[0]["summary"] == "Lunch at Market 57")
check("tz preserved", evs[0]["ended_at"].tzinfo is not None)

fenced = "```json\n" + good + "\n```"
check("code-fenced JSON parsed", len(parse_scan_reply(fenced)) == 1)

naive = '{"events": [{"summary": "x y z long", "ended_at": "2026-06-30T13:30:00", "followed_up": true}]}'
evs = parse_scan_reply(naive)
check("naive datetime treated as UTC",
      evs and evs[0]["ended_at"].utcoffset() == timedelta(0))
check("followed_up carried through", evs and evs[0]["followed_up"] is True)

check("garbage → empty", parse_scan_reply("no json here") == [])
check("missing ended_at dropped",
      parse_scan_reply('{"events": [{"summary": "x"}]}') == [])
check("empty events ok", parse_scan_reply('{"events": []}') == [])

# --------------------------------------------------------------------------- #
print("followup — prompts keep the silence escape:")
cp = build_checkin_prompt("Lunch at Market 57", "Tuesday Jun 30, 1:30 PM")
sp = build_suggest_prompt("Lunch at Market 57", "Tuesday Jun 30, 1:30 PM")
check("checkin prompt has '...' escape", '"..."' in cp)
check("checkin prompt honors butt-out", "stay out" in cp)
check("suggest prompt has '...' escape", '"..."' in sp)
check("suggest prompt demands real options", "places" in sp or "web_search" in sp)
check("checkin includes the event", "Market 57" in cp)

# --------------------------------------------------------------------------- #
print("rich links:")
from hal_orchestrator.tools.places import FIELD_MASK, MAX_PHOTOS  # noqa: E402
from hal_orchestrator.tools.travel_time import directions_link  # noqa: E402

link = directions_link("Chelsea, Manhattan", "Pier 57, NYC", "walk")
check("directions link uses api=1 deep-link", link.startswith("https://www.google.com/maps/dir/?api=1"))
check("origin/destination url-encoded", "Chelsea%2C+Manhattan" in link and "Pier+57%2C+NYC" in link)
check("walk → walking travelmode", link.endswith("travelmode=walking"))
check("unknown mode falls back to driving",
      directions_link("a", "b", "hovercraft").endswith("travelmode=driving"))
check("places field mask requests photos", "places.photos.name" in FIELD_MASK)
check("photo attach cap is sane", 1 <= MAX_PHOTOS <= 3)

# --------------------------------------------------------------------------- #
print("calendar — relative day labels computed in code (the 7/6 'tomorrow' bug):")
from zoneinfo import ZoneInfo  # noqa: E402

from hal_orchestrator.tools.google import format_event_when  # noqa: E402

_ET = ZoneInfo("America/New_York")
_now = datetime(2026, 7, 6, 8, 0, tzinfo=_ET)
w = format_event_when("2026-07-08T15:10:00-04:00", _now, _ET)
check("7/8 seen from 7/6 is 'in 2 days', never tomorrow", "(in 2 days)" in w, w)
check("absolute time still shown", "Jul 8" in w and "3:10 PM" in w, w)
check("7/7 is TOMORROW", "(TOMORROW)" in format_event_when("2026-07-07T09:00:00-04:00", _now, _ET))
check("7/6 evening is TODAY", "(TODAY)" in format_event_when("2026-07-06T19:00:00-04:00", _now, _ET))
check("all-day event labeled", "(all day)" in format_event_when("2026-07-08", _now, _ET))
check("all-day 7/8 also 'in 2 days'", "(in 2 days)" in format_event_when("2026-07-08", _now, _ET))
check("late-night tz boundary: 7/7 4am UTC = 7/7 0am ET is TOMORROW",
      "(TOMORROW)" in format_event_when("2026-07-07T04:00:00+00:00", _now, _ET))
check("naive datetime anchored to user tz",
      "(TOMORROW)" in format_event_when("2026-07-07T09:00:00", _now, _ET))
check("garbage start survives", format_event_when("not-a-date", _now, _ET) == "not-a-date")
check("missing start survives", format_event_when(None, _now, _ET) == "?")

print("followup — silo allowlist:")
from hal_orchestrator.services.followup import allowed_silo  # noqa: E402

check("empty allowlist allows all", allowed_silo("chat123", ""))
check("listed silo allowed", allowed_silo("+12017570419", "+12017570419, chat99"))
check("unlisted silo blocked", not allowed_silo("chat123", "+12017570419"))

# --------------------------------------------------------------------------- #
print("playbook — scope plumbing:")
from hal_orchestrator.services import playbook as pb  # noqa: E402

check("scopes defined", pb.SCOPES == ("dm", "group", "all"))
check("cache is per-scope dict", isinstance(pb._cache.get("blocks"), dict))

# --------------------------------------------------------------------------- #
print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
