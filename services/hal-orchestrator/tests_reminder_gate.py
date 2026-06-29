"""Tests for the fire-time reminder relevance gate
(hal_orchestrator.services.reminders).

The gate's *decision* is the background model's; what's deterministic — and
what breaks silently if it regresses — is (a) how the model's reply is turned
into a keep/drop/reword action, and (b) that the live situation + cancel
condition actually reach the model. Those are pure and tested here. The
end-to-end DB + live-model path (log an early nap -> wind-down gated out) is
exercised against a real model, not this harness.

Run: python3 services/hal-orchestrator/tests_reminder_gate.py
"""

import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services.reminders import (  # noqa: E402
    build_gate_prompt,
    parse_gate_verdict,
)

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


print("parse_gate_verdict — drop:")
for reply in ["DROP", "drop", "Drop", "  DROP  ", "DROP — he's already asleep",
              "DROP\n(already napping)"]:
    v = parse_gate_verdict(reply)
    check(f"{reply!r} -> drop", v.drop and v.text is None, f"got {v}")

print("parse_gate_verdict — send as-is:")
for reply in ["SEND", "send", "  SEND  ", "SEND\nstill relevant"]:
    v = parse_gate_verdict(reply)
    check(f"{reply!r} -> send/keep", (not v.drop) and v.text is None, f"got {v}")

print("parse_gate_verdict — send reworded:")
v = parse_gate_verdict("SEND: Bottle prep — next feed now ~10:30 AM")
check("reworded text extracted",
      (not v.drop) and v.text == "Bottle prep — next feed now ~10:30 AM", f"got {v}")
v = parse_gate_verdict("send: 🍼 prep a bottle")
check("lowercase send: reworded", (not v.drop) and v.text == "🍼 prep a bottle", f"got {v}")
v = parse_gate_verdict("SEND:   ")
check("SEND with empty rewrite keeps original", (not v.drop) and v.text is None, f"got {v}")
v = parse_gate_verdict("SEND: leave by 4:15 — note: traffic on I-95")
check("only first colon splits the rewrite",
      v.text == "leave by 4:15 — note: traffic on I-95", f"got {v}")

print("parse_gate_verdict — fail-open (never silently drop on junk):")
for reply in ["", "   ", None, "maybe?", "I think you should keep it"]:
    v = parse_gate_verdict(reply)
    check(f"{reply!r} -> send", (not v.drop) and v.text is None, f"got {v}")

print("build_gate_prompt:")
p = build_gate_prompt(
    reminder_text="💤 Start winding Bazzy down — next nap looks like ~9:33 AM",
    cancel_if="Bazzy is already asleep",
    situation="Bazzy is napping (since 9:10 AM)\nExpected wake: ~10:00 AM",
    now_str="Mon Jun 29 9:18 AM",
)
check("includes reminder text", "winding Bazzy down" in p)
check("includes cancel condition", "already asleep" in p)
check("includes live situation", "napping (since 9:10 AM)" in p)
check("includes current time", "9:18 AM" in p)
check("offers DROP / SEND / SEND: contract",
      "DROP" in p and "SEND" in p and "SEND: <new text>" in p)

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
