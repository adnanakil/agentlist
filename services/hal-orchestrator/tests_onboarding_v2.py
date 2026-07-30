"""Tests for the delightful-onboarding revamp (2026-07-09):

  1. value-first first contact          (prompts/system._onboarding_block)
  2. group-aware warm start + name pre-fill
  3. code-enforced ask decay + completion not blocked by declined facts
  4. google offer/disconnect flag behaviour
  5. trial-brief state machine (armed -> asked -> off-if-silent, commit clears)
  6. onboarding funnel accounting (compute_onboarding_progress)

Pure-function style — no DB, no network (a tiny fake session covers the one
tool that needs `session.execute`). Run:
    uv run python tests_onboarding_v2.py
"""

import asyncio
import os
import sys
from types import SimpleNamespace

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.prompts.system import (
    ONBOARDING_ASK_CAP,
    _onboarding_block,
    compute_onboarding_progress,
    is_onboarding_complete,
    next_onboarding_step,
    plausible_personal_name,
)
from hal_orchestrator.services.helpful import (
    TRIAL_FOLLOWUP,
    _trial_expired,
    advance_trial_on_brief,
)
from hal_orchestrator.services.profiles import _empty
from hal_orchestrator.tools.helpful import tool_helpful

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


base = _empty("+15550009999")
FACTS = {
    "name": "Al",
    "timezone": "America/Los_Angeles",
    "home_location": "Venice",
    "work_location": "Santa Monica",
}


# --- 1. value-first first contact ------------------------------------------- #
print("value-first first contact:")
b0 = _onboarding_block(base)
check("cold first contact answers a real request first", b0 and "ANSWER it" in b0)
check("cold first contact still asks the name", b0 and "call them" in b0)
check("cold first contact introduces HAL", b0 and "proactive assistant" in b0)


# --- 2. group-aware warm start + name pre-fill ------------------------------ #
print("\ngroup-aware warm start:")
bg = _onboarding_block(base, group_intro="Mattituck crew")
check("group name-step places HAL in the shared chat", bg and "Mattituck crew" in bg)
check("group name-step is not a cold intro", bg and "HAL from the Mattituck crew" in bg)

# Name pre-filled (group member) -> name step skipped, warm-start header shown
# on the FIRST onboarding turn only.
prefilled = {**base, "name": "Al"}
bw = _onboarding_block(prefilled, group_intro="Book Club")
check("pre-filled name skips to timezone", bw and "timezone" in bw.lower())
check("warm-start header shown on first turn", bw and "Book Club" in bw)
after_turn = {**prefilled, "onboarding_events": [{"step": "timezone", "event": "asked"}]}
bw2 = _onboarding_block(after_turn, group_intro="Book Club")
check("warm-start header NOT repeated after first turn", bw2 and "Book Club" not in bw2)

print("\nplausible_personal_name:")
check("real name accepted", plausible_personal_name("Joyce") == "Joyce")
check("two-word name accepted", plausible_personal_name("  Mary  Beth ") == "Mary Beth")
check("empty -> None", plausible_personal_name("") is None)
check("None -> None", plausible_personal_name(None) is None)
check("phone-like -> None", plausible_personal_name("+1 555 0100") is None)
check("email-like -> None", plausible_personal_name("al@x.com") is None)
check("single char -> None", plausible_personal_name("A") is None)


# --- 3. code-enforced ask decay --------------------------------------------- #
print("\nask decay:")
check("brand-new -> name", next_onboarding_step(base) == "name")
check(
    "name asked once still asked",
    next_onboarding_step({**base, "asked_name": 1}) == "name",
)
check(
    "name asked to cap -> skip to timezone",
    next_onboarding_step({**base, "asked_name": ONBOARDING_ASK_CAP}) == "timezone",
)
# A user who declines EVERY fact (each asked to the cap) + google offered still
# reaches 'done' — never un-onboardable.
declined = {
    **base,
    "asked_name": ONBOARDING_ASK_CAP,
    "asked_timezone": ONBOARDING_ASK_CAP,
    "asked_home": ONBOARDING_ASK_CAP,
    "asked_work": ONBOARDING_ASK_CAP,
    "google_offered": True,
}
check("fully-declined user -> done", next_onboarding_step(declined) == "done")
check("fully-declined user is complete", is_onboarding_complete(declined))
check(
    "declined but google not offered -> still google step",
    next_onboarding_step({**declined, "google_offered": False}) == "google",
)
# Sync contract: is_onboarding_complete tracks next_onboarding_step == done.
check("all facts set, google offered -> complete", is_onboarding_complete({**base, **FACTS, "google_offered": True}))
check("all facts set, no google -> incomplete", not is_onboarding_complete({**base, **FACTS}))
check("onboarded flag short-circuits complete", is_onboarding_complete({**base, "onboarded": True}))


# --- 4. google offer / disconnect flags ------------------------------------- #
print("\ngoogle offer / disconnect:")
allfacts = {**base, **FACTS}
check("all facts, nothing google -> offer google", next_onboarding_step(allfacts) == "google")
check("google offered -> done", next_onboarding_step({**allfacts, "google_offered": True}) == "done")
check("google connected -> done", next_onboarding_step({**allfacts, "google_connected": True}) == "done")
check(
    "google disconnected -> done (never re-pitched)",
    next_onboarding_step({**allfacts, "google_disconnected": True}) == "done",
)
check(
    "disconnected user is complete",
    is_onboarding_complete({**allfacts, "google_disconnected": True}),
)
# Offer step sets expectations (change 4a).
goog = _onboarding_block(allfacts)
check("offer step sets expectations (never sends as them)", goog and "NEVER send" in goog)
check("offer step marks google_offered", goog and "google_offered=true" in goog)


# --- 5. trial-brief state machine ------------------------------------------- #
print("\ntrial-brief state machine (pure):")
check("_trial_expired: same day -> False", _trial_expired("2026-07-09", "2026-07-09") is False)
check("_trial_expired: next day -> True", _trial_expired("2026-07-09", "2026-07-10") is True)
check("_trial_expired: no date -> False", _trial_expired(None, "2026-07-10") is False)

hp = {"enabled": True, "trial": "armed"}
was_trial = advance_trial_on_brief(hp, "2026-07-09")
check("armed brief -> asked + dated + returns True", was_trial and hp["trial"] == "asked" and hp["trial_asked_date"] == "2026-07-09")
check("asked brief again -> not a trial send", advance_trial_on_brief(hp, "2026-07-10") is False)
committed = {"enabled": True}
check("no trial -> advance is a no-op", advance_trial_on_brief(committed, "2026-07-09") is False)
check("follow-up line asks about daily", "every morning" in TRIAL_FOLLOWUP)

# done step arms the trial (change 5).
done = _onboarding_block({**allfacts, "google_offered": True})
check("done step arms the trial brief", done and "helpful_mode(action=trial)" in done)
check("done step leaves the flag to the code backstop",
      done and "recorded automatically" in done and "onboarded=true" not in done)


# --- helpful tool: trial arms; on/off commit/clear -------------------------- #
print("\nhelpful tool trial transitions:")


class FakeProfile:
    def __init__(self):
        self.phone = "+15550009999"
        self.extra_data = {}


class FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class FakeSession:
    def __init__(self, obj):
        self._obj = obj

    async def execute(self, stmt):
        return FakeResult(self._obj)

    async def flush(self):
        pass


async def run_tool_checks():
    prof = FakeProfile()
    ctx = SimpleNamespace(phone=prof.phone, session=FakeSession(prof))
    await tool_helpful({"action": "trial"}, ctx)
    hp = prof.extra_data.get("helpful") or {}
    check("tool trial -> enabled + armed", hp.get("enabled") is True and hp.get("trial") == "armed")

    # simulate the sample brief having been asked, then commit via action=on
    prof.extra_data = {"helpful": {"enabled": True, "trial": "asked", "trial_asked_date": "2026-07-09"}}
    await tool_helpful({"action": "on"}, ctx)
    hp = prof.extra_data.get("helpful") or {}
    check("tool on commits (clears trial)", hp.get("enabled") is True and "trial" not in hp)

    prof.extra_data = {"helpful": {"enabled": True, "trial": "asked", "trial_asked_date": "2026-07-09"}}
    await tool_helpful({"action": "off"}, ctx)
    hp = prof.extra_data.get("helpful") or {}
    check("tool off clears trial + disables", hp.get("enabled") is False and "trial" not in hp)


asyncio.run(run_tool_checks())


# --- 6. onboarding funnel accounting ---------------------------------------- #
print("\nonboarding funnel (compute_onboarding_progress):")

# Asked (unanswered) -> increment + asked event.
upd, evs = compute_onboarding_progress(base, base)
check("unanswered name -> asked_name incremented to 1", upd.get("asked_name") == 1)
check("unanswered name -> 'asked' event", any(e["kind"] == "asked" and e["step"] == "name" for e in evs))
check("asked event carries the timeline", any(x.get("event") == "asked" for x in upd.get("onboarding_events", [])))
# Emitted events must be structlog-safe: NO reserved 'event' key (would collide
# with structlog's log.info(event, ...) and raise, breaking post-hooks).
check("emitted events have no reserved 'event' key", all("event" not in e for e in evs))

# Answered this turn -> answered event, no increment.
post_named = {**base, "name": "Al"}
upd2, evs2 = compute_onboarding_progress(base, post_named)
check("answered name -> no asked_name increment", "asked_name" not in upd2)
check("answered name -> 'answered' event", any(e["kind"] == "answered" and e["step"] == "name" for e in evs2))

# Skipped-by-decay: name decayed + unset, flow now on timezone.
pre_decayed = {**base, "asked_name": ONBOARDING_ASK_CAP}
upd3, evs3 = compute_onboarding_progress(pre_decayed, pre_decayed)
check("decayed name -> 'skipped_decay' event", any(e["kind"] == "skipped_decay" and e["step"] == "name" for e in evs3))
check("decayed name + unanswered tz -> asked_timezone incremented", upd3.get("asked_timezone") == 1)

# Completion: terminal reached this turn.
pre_terminal = {**base, **FACTS}  # google not yet offered -> step 'google'
post_terminal = {**base, **FACTS, "google_offered": True}  # -> 'done'
upd4, evs4 = compute_onboarding_progress(pre_terminal, post_terminal)
check("reaching terminal -> 'completed' event", any(e["kind"] == "completed" for e in evs4))
check("completion stamps onboarded_at", bool(upd4.get("onboarded_at")))

# Idempotence: already-onboarded pre -> nothing.
upd5, evs5 = compute_onboarding_progress({**base, "onboarded": True}, {**base, "onboarded": True})
check("already onboarded -> no updates/events", upd5 == {} and evs5 == [])

# Don't double-log an event already in the timeline.
pre_has_answered = {**base, "name": "Al", "onboarding_events": [{"step": "name", "event": "answered", "at": "x"}]}
# name is set so flow is on timezone; feed an unanswered tz to make it a normal turn
upd6, evs6 = compute_onboarding_progress(pre_has_answered, pre_has_answered)
check("existing answered event not re-emitted", not any(e["kind"] == "answered" and e["step"] == "name" for e in evs6))


print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all passed")
