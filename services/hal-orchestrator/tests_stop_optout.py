"""Tests for STOP / opt-out and the delete-me forget aliases
(hal_orchestrator.services.optout).

What's deterministic — and what breaks silently if it regresses — is (a) the
whole-message phrase matching + normalization the route keys off, and (b) that
the route, the outbox (delivery.enqueue), and the follow-up sweep are actually
wired to the optout module. The DB round-trip (flag set -> enqueue drops) runs
against Postgres in prod verification, not this harness.

Run: python3 services/hal-orchestrator/tests_stop_optout.py
"""

import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services.optout import (  # noqa: E402
    FORGET_PHRASES,
    START_PHRASES,
    STOP_PHRASES,
    normalize,
)

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


print("normalize:")
for raw, want in [
    ("STOP", "stop"),
    (" Stop! ", "stop"),
    ("stop.", "stop"),
    ("STOP!!!", "stop"),
    ("Delete Me", "delete me"),
    ("Delete Me.", "delete me"),
    ("  FORGET ME?  ", "forget me"),
    ("stop …", "stop"),
    ("", ""),
    (None, ""),
]:
    got = normalize(raw)
    check(f"{raw!r} -> {want!r}", got == want, f"got {got!r}")

print("\nSTOP keywords (whole message, any casing/punctuation):")
for msg in ["stop", "STOP", "Stop!", "stopall", "STOP ALL", "unsubscribe",
            "Opt Out", "optout", "stop texting me", "Stop messaging me.",
            "don't text me", "dont text me", "do not text me"]:
    check(f"{msg!r} opts out", normalize(msg) in STOP_PHRASES)

print("\nconversational near-misses must NOT opt out:")
for msg in ["stop it", "please stop", "stop the reminder", "can you stop",
            "cancel", "end", "quit", "cancel that reminder", "stop by the store",
            "never stop"]:
    check(f"{msg!r} stays conversational", normalize(msg) not in STOP_PHRASES)

print("\nSTART keywords (resume, only consulted while stopped):")
for msg in ["start", "START", "unstop", "resume", "Subscribe", "opt in", "start again"]:
    check(f"{msg!r} resumes", normalize(msg) in START_PHRASES)

print("\ndelete-me arms the forget flow:")
for msg in ["delete me", "Delete Me", "DELETE ME!", "forget me", "/forget",
            "/delete", "delete my data", "Delete my account."]:
    check(f"{msg!r} arms forget", normalize(msg) in FORGET_PHRASES)
for msg in ["delete everything", "delete the reminder", "delete that"]:
    check(f"{msg!r} does not arm forget", normalize(msg) not in FORGET_PHRASES)

print("\nphrase sets are disjoint (one message, one meaning):")
check("STOP ∩ START empty", not (STOP_PHRASES & START_PHRASES))
check("STOP ∩ FORGET empty", not (STOP_PHRASES & FORGET_PHRASES))
check("START ∩ FORGET empty", not (START_PHRASES & FORGET_PHRASES))
check("confirm phrase not a keyword",
      "delete everything" not in STOP_PHRASES | START_PHRASES | FORGET_PHRASES)

print("\nwiring (the gates actually exist where they must):")
_HERE = os.path.dirname(os.path.abspath(__file__))


def _src(rel):
    with open(os.path.join(_HERE, "hal_orchestrator", rel)) as f:
        return f.read()


route = _src("routes/message.py")
check("route imports optout phrase sets",
      "STOP_PHRASES" in route and "FORGET_PHRASES" in route)
check("route marks stopped on STOP", "mark_stopped(session, silo)" in route)
check("route stays silent while stopped", "optout.inbound_suppressed" in route)
check("route resumes on START", "clear_stopped(session, silo)" in route)
check("route normalizes via optout", "_lower = normalize(user_text)" in route)

delivery = _src("services/delivery.py")
check("outbox enqueue gates on is_stopped",
      "is_stopped(session, to)" in delivery
      and "outbox.suppressed_stopped" in delivery)

followup = _src("services/followup.py")
check("follow-up sweep skips stopped silos", "is_stopped(session, silo)" in followup)

profiles = _src("services/profiles.py")
check("stopped_at registered as a profile extra key", '"stopped_at",' in profiles)

prompts = _src("prompts/system.py")
check("model told to honor natural-language stop", "OPT-OUT" in prompts)

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("all checks passed")
