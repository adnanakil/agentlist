"""Tests for the parent onboarding track (beachhead front door — ONBOARDING.md):

  1. track detection (landing prefill + code, tight baby-intent, no false flips)
  2. parent step machine: baby → city → name(cap 1) → done; Google never offered
  3. parent onboarding block content (value-first, one question, scripts)
  4. parent playbook scripts present (privacy verbatim, twins, Android, export)
  5. funnel accounting on the parent track (asked_baby / asked_city / name cap)
  6. age-normed wake windows + forecast confidence presentation
  7. create_family timezone handling (tz_set marker, no silent NY default)
  8. landing renderer (?c= code → prefill; privacy line verbatim)

Pure-function style — no DB, no network. Run:
    uv run python tests_onboarding_parent.py
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.prompts.system import (
    PARENT_PLAYBOOK,
    PARENT_TRACK,
    _onboarding_block,
    compute_onboarding_progress,
    detect_onboarding_track,
    is_onboarding_complete,
    next_onboarding_step,
)
from hal_orchestrator.routes.landing import SMS_PREFILL, render_landing
from hal_orchestrator.services.baby import (
    DEFAULT_WAKE_WINDOW_MIN,
    default_wake_window_min,
    forecast_next,
    format_forecast,
)
from hal_orchestrator.services.profiles import _empty

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


base = _empty("+15550007777")
parent = {**base, "onboarding_track": PARENT_TRACK}


# --- 1. track detection ------------------------------------------------------ #
print("track detection:")
t, code, clean = detect_onboarding_track("Hi HAL — new baby here 👶")
check("landing prefill -> parent", t == PARENT_TRACK and code is None)
t, code, clean = detect_onboarding_track("Hi HAL — new baby here 👶 (reddit-x1)")
check("prefill code parsed", t == PARENT_TRACK and code == "reddit-x1")
check("prefill code stripped from text", "(reddit-x1)" not in clean and "new baby" in clean)
t, _, _ = detect_onboarding_track("she ate 4oz at 3:15")
check("oz pattern -> parent", t == PARENT_TRACK)
t, _, _ = detect_onboarding_track("just had a baby last week!!")
check("'just had a baby' -> parent", t == PARENT_TRACK)
t, _, _ = detect_onboarding_track("my daughter is 7 weeks old")
check("age pattern -> parent", t == PARENT_TRACK)
t, _, _ = detect_onboarding_track("is 4oz normal for a 7 week old?")
check("question with baby intent -> parent", t == PARENT_TRACK)
t, _, _ = detect_onboarding_track("diaper run before the game?")
check("diaper -> parent", t == PARENT_TRACK)
t, _, _ = detect_onboarding_track("I need a nap after that meeting")
check("adult 'nap' does NOT flip", t is None)
t, _, _ = detect_onboarding_track("feed the dog at 6 please remind me")
check("adult 'feed' does NOT flip", t is None)
t, _, _ = detect_onboarding_track("hey HAL")
check("generic hello does NOT flip", t is None)
t, _, _ = detect_onboarding_track("what's the weather like")
check("weather q does NOT flip", t is None)


# --- 2. parent step machine -------------------------------------------------- #
print("\nparent step machine:")
check("parent brand-new -> baby", next_onboarding_step(parent) == "baby")
with_baby = {**parent, "baby_name": "Leo"}
check("baby set -> city", next_onboarding_step(with_baby) == "city")
with_city = {**with_baby, "timezone": "America/Chicago"}
check("city (tz) set -> name", next_onboarding_step(with_city) == "name")
with_name = {**with_city, "name": "Sam"}
check("all parent facts -> done (NO google step)", next_onboarding_step(with_name) == "done")
check("parent flow complete without google", is_onboarding_complete(with_name))
# name cap is ONE — a single unanswered ask decays it.
name_asked_once = {**with_city, "asked_name": 1}
check("name asked once -> done (cap 1)", next_onboarding_step(name_asked_once) == "done")
check("name-declined parent is complete", is_onboarding_complete(name_asked_once))
# baby/city keep the standard cap of 2.
check(
    "baby asked once still asked",
    next_onboarding_step({**parent, "asked_baby": 1}) == "baby",
)
check(
    "baby asked to cap -> city",
    next_onboarding_step({**parent, "asked_baby": 2}) == "city",
)
check(
    "city asked to cap -> name",
    next_onboarding_step({**with_baby, "asked_city": 2}) == "name",
)
# google flags NEVER gate the parent track.
check(
    "google flags ignored on parent track",
    next_onboarding_step({**with_name, "google_offered": False}) == "done",
)
# generic track unchanged.
check("generic brand-new -> name", next_onboarding_step(base) == "name")


# --- 3. parent onboarding block ---------------------------------------------- #
print("\nparent onboarding block:")
b = _onboarding_block(parent)
check("baby step is value-first (loggable event handled first)", b and "LOGGABLE" in b)
check("baby step answers questions first", b and "QUESTION" in b)
check("baby step asks name AND age", b and "how old" in b)
check("baby step never repeats a reported event", b and "NEVER make them repeat" in b)
check("baby step calls setup with birthdate", b and "baby(action=setup" in b)
check("parent header caps at three questions", b and "three questions" in b)
bc = _onboarding_block(with_baby)
check("city step asks the city", bc and "city" in bc.lower())
check("city step saves tz to BOTH profile and family", bc and "baby(action=configure, timezone=" in bc)
check("city step captured line shows baby", bc and "baby=Leo" in bc)
bn = _onboarding_block(with_city)
check("name step is woven, never a blocker", bn and "NEVER as a blocker" in bn)
bd = _onboarding_block(name_asked_once)
check("done step flips onboarded", bd and "onboarded=true" in bd)
check("done step arms the trial brief", bd and "helpful_mode(action=trial)" in bd)
check("done step invites backfill", bd and "backfill" in bd)
check("done step forbids feature pitches", bd and "do NOT pitch features" in bd)


# --- 4. parent playbook scripts ---------------------------------------------- #
print("\nparent playbook:")
check(
    "privacy answer verbatim",
    "Your family's data stays yours — never sold, never ads, never used to "
    "train anything. Text 'forget me' and it's gone." in PARENT_PLAYBOOK,
)
check("ambiguous-time confirm-back rule", "BEFORE logging" in PARENT_PLAYBOOK)
check("backfill count-match rule", "count must match" in PARENT_PLAYBOOK)
check("twins honesty script", "one log per family" in PARENT_PLAYBOOK)
check("android partner script", "iMessage today" in PARENT_PLAYBOOK)
check("second-caregiver how-to", "Add Contact" in PARENT_PLAYBOOK)
check("import/export answer", "baby(action=export)" in PARENT_PLAYBOOK)
check("medical boundary present", "nurse line" in PARENT_PLAYBOOK)
check("overwhelmed script tracks less", "track LESS" in PARENT_PLAYBOOK)


# --- 5. funnel accounting on the parent track -------------------------------- #
print("\nparent funnel accounting:")
upd, evs = compute_onboarding_progress(parent, parent)
check("unanswered baby -> asked_baby incremented", upd.get("asked_baby") == 1)
check("asked event step=baby", any(e["kind"] == "asked" and e["step"] == "baby" for e in evs))
upd2, evs2 = compute_onboarding_progress(parent, {**parent, "baby_name": "Leo"})
check("answered baby -> answered event, no increment", "asked_baby" not in upd2
      and any(e["kind"] == "answered" and e["step"] == "baby" for e in evs2))
# name asked once (cap 1) then unanswered on the next turn -> decay + completion.
pre = {**with_city, "asked_name": 1}
upd3, evs3 = compute_onboarding_progress(pre, pre)
check("name decayed after ONE ask", any(e["kind"] == "skipped_decay" and e["step"] == "name" for e in evs3))
check("parent completion fires without google", any(e["kind"] == "completed" for e in evs3))
check("completion stamps onboarded_at", bool(upd3.get("onboarded_at")))


# --- 6. age-normed wake windows + forecast confidence ------------------------ #
print("\nage-normed forecast:")
now = datetime(2026, 7, 18, 15, 0, tzinfo=timezone.utc)
nyc = ZoneInfo("America/New_York")
seven_weeks = now.date() - timedelta(weeks=7)
six_months = now.date() - timedelta(days=180)
check("no birthdate -> generic default", default_wake_window_min(None, now) == DEFAULT_WAKE_WINDOW_MIN)
check("7-week-old window ~60min", default_wake_window_min(seven_weeks, now) == 60)
check("newborn window 45min", default_wake_window_min(now.date() - timedelta(days=10), now) == 45)
check("6-month window 120min", default_wake_window_min(six_months, now) == 120)
check("18-month+ window 330min", default_wake_window_min(now.date() - timedelta(days=700), now) == 330)
check("future birthdate -> generic default", default_wake_window_min(now.date() + timedelta(days=30), now) == DEFAULT_WAKE_WINDOW_MIN)

# Sparse data: wake 1h ago, one earlier nap — forecast for a 7-week-old should
# project the age window (60m), and format as a humble RANGE, not a point.
events = [
    ("nap_start", now - timedelta(hours=2)),
    ("wake", now - timedelta(hours=1)),
]
fc = forecast_next(events, nyc, now, birthdate=seven_weeks)
check("sparse forecast uses age window",
      fc["next_nap"] == now - timedelta(hours=1) + timedelta(minutes=60),
      f"got {fc['next_nap']}")
check("sparse forecast exposes sample count", fc["patterns"].get("wake_window_samples") == 0)
txt = format_forecast(fc, nyc, "Leo", now)
check("sparse forecast renders as a window", "sleepy window" in txt and "–" in txt)
check("sparse forecast admits it's age-typical", "age-typical" in txt)
check("sparse forecast promises sharpening", "sharpens" in txt)

# Rich data (>=3 observed windows) -> confident point estimate, no humility tag.
rich = []
t0 = now - timedelta(days=1)
for i in range(4):
    rich.append(("wake", t0 + timedelta(hours=3 * i)))
    rich.append(("nap_start", t0 + timedelta(hours=3 * i, minutes=90)))
rich.append(("wake", now - timedelta(minutes=30)))
fc2 = forecast_next(rich, nyc, now, birthdate=seven_weeks)
check("rich data -> enough samples", fc2["patterns"]["wake_window_samples"] >= 3)
txt2 = format_forecast(fc2, nyc, "Leo", now)
check("rich forecast is a point estimate", "age-typical" not in txt2)


# --- 7. create_family timezone handling (signature-level, no DB) ------------- #
print("\ncreate_family timezone:")
import inspect

from hal_orchestrator.services.baby import create_family

sig = inspect.signature(create_family)
check("create_family accepts timezone_name", "timezone_name" in sig.parameters)
check("create_family accepts baby_birthdate", "baby_birthdate" in sig.parameters)
check("timezone_name defaults to None (caller decides)",
      sig.parameters["timezone_name"].default is None)


# --- 8. landing renderer ----------------------------------------------------- #
print("\nlanding renderer:")
html = render_landing("+15550001234")
check("hero is the beachhead line", "The baby log that lives in your group chat." in html)
check("sms prefill is the parent selector", "new%20baby%20here" in html)
check("privacy line verbatim", "never sold, never ads" in html and "forget me" in html)
html_code = render_landing("+15550001234", code="psp-01")
check("?c= code lands in the prefill", "%28psp-01%29" in html_code)
check("no code -> no parens in prefill", "%28" not in html.split("footer")[0])
check("prefill constant matches detection", detect_onboarding_track(SMS_PREFILL)[0] == PARENT_TRACK)
coming = render_landing("")
check("coming-soon variant still renders", "coming soon" in coming)


print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all passed")
