"""Tests for heartbeat silence-sentinel handling (the GLM 'leaked sentinel' spam
fix). Catches the sentinel whether GLM puts it leading, trailing, or on its own
line. Pure-string logic; no network/db.

Run: python3 services/hal-orchestrator/tests_heartbeat_sentinel.py
"""

import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.routes.message import (
    _contains_quiet_sentinel,
    _is_quiet_sentinel,
    _is_repeat_alert,
)


def _m(text):
    return {"role": "model", "parts": [{"text": text}]}

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


print("pure sentinel still detected by _is_quiet_sentinel (unchanged):")
for s in ["...", "…", "  ...  ", ".. .", ""]:
    check(f"pure {s!r} -> quiet", _is_quiet_sentinel(s))

print("\nLEADING sentinel ramble -> contains TRUE (suppressed for internal):")
for s in [
    "... All marketing/newsletters — Dover Street Market, Kith Kids, Bode, Hulu",
    "…nothing upcoming in the next 2 hours, inbox is all noise",
]:
    check(f"{s[:30]!r}", _contains_quiet_sentinel(s))

print("\nTRAILING sentinel ramble (the real 06-27 message) -> contains TRUE:")
real_leak = (
    "It's 1:39 AM on Saturday night — Adnan's likely winding down from the match "
    "and the TikTok discussion. Nothing upcoming on the calendar, and the inbox is "
    "all promos/newsletters (Nextdoor, Lyft receipt, Zillow, Reddit, ICNYC survey, "
    "Amazon review request) — all machine-generated, no real person replies or "
    "deliveries. Nothing new worth flagging that I haven't already mentioned.\n\n..."
)
check("trailing '...' on own line", _contains_quiet_sentinel(real_leak))
check("  (and NOT caught by pure-sentinel check)", not _is_quiet_sentinel(real_leak))
check("trailing '...' same line", _contains_quiet_sentinel("Nothing worth flagging right now ..."))
check("standalone '...' mid-message", _contains_quiet_sentinel("Thinking about it.\n...\nNothing to add."))

print("\nreal proactive alerts -> contains FALSE (still sent):")
for s in [
    "Heads up — you have an unread email from StubHub; accept your tickets.",
    "Heads up if you're driving back from Mattituck — traffic building on the LIE.",
    "NJ Transit receipt — looks like you bought tickets for tomorrow's MetLife trip.",
    "It's 7am Friday — you're probably packing up to head back to Chelsea today.",
]:
    check(f"NOT suppressed {s[:30]!r}", not _contains_quiet_sentinel(s))

print("\nedge cases (must NOT be treated as a sentinel):")
check(".NET not suppressed", not _contains_quiet_sentinel(".NET 9 update is available"))
check("inline ellipsis 'at 9...' not suppressed", not _contains_quiet_sentinel("Your flight is delayed at 9..."))
check("single leading dot not suppressed", not _contains_quiet_sentinel(". one thing came up"))
check("dash bullets not suppressed", not _contains_quiet_sentinel("- Traffic on the LIE\n- Rain at 5pm"))
check("sentence ending in period not suppressed", not _contains_quiet_sentinel("Leave by 9:15 to make it."))

print("\nrepeat-alert cap (_is_repeat_alert, cap=2): muzzle re-alerts about ONE event:")
# the real 06-27 bug: identical "leave by 3:30 for the 5pm match" over and over
_leave = ("Match day — Panama vs England kicks off at 5pm at MetLife! Aim to leave "
          "Chelsea by 3:30pm. NJ Transit Penn to Secaucus, Saturday crowds pack the trains.")
hist2 = [_m(_leave), _m("unrelated: your StubHub tickets are ready to download.")]
check("3rd identical 'leave by 3:30' -> repeat (suppressed)",
      _is_repeat_alert(_leave, [_m(_leave)] + hist2))
check("1st time (empty history) -> NOT a repeat", not _is_repeat_alert(_leave, []))
check("2nd time (one prior, cap=2) -> NOT yet capped", not _is_repeat_alert(_leave, [_m(_leave)]))

# the 06-28 bug: World-Cup-pool countdown — numbers differ, content is the same
_pool1 = "Reminder — send Isabelle your 8 World Cup pool picks before the noon deadline! About an hour left."
_pool2 = "Last call — 28 minutes until the noon World Cup pool deadline. Send Isabelle your 8 picks!"
_pool3 = "13 minutes left! Send Isabelle your 8 World Cup pool picks before noon."
check("3rd pool countdown -> repeat (suppressed despite different numbers)",
      _is_repeat_alert(_pool3, [_m(_pool1), _m(_pool2)]))

print("\nrepeat-alert cap must NOT muzzle genuinely DIFFERENT alerts:")
check("distinct alert (rain vs the leave-alert) -> NOT a repeat",
      not _is_repeat_alert("Heads up — thunderstorms rolling into East Rutherford around 5pm.",
                           [_m(_leave), _m(_leave)]))
# Omar/Louay accepted tickets: near-identical, but only 2 of them -> both go out
_omar = "Omar just accepted and downloaded the tickets you sent. Kickoff is at 5pm!"
_louay = "Louay just accepted and downloaded the tickets too. Kickoff is at 5pm!"
check("2nd ticket-acceptance (Louay after Omar, cap=2) -> still sent",
      not _is_repeat_alert(_louay, [_m(_omar)]))
check("very short alert -> never capped (too few words to match)",
      not _is_repeat_alert("Package delivered.", [_m("Package delivered."), _m("Package delivered.")]))

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
