"""Tests for the growth loop's pure logic: scrubbing, privacy lint, JSON
parsing, and the refusal heuristic.

Run: python3 services/hal-orchestrator/tests_growth.py
"""

import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services.growth import parse_json_block, scrub
from hal_orchestrator.services.playbook import lint_violation
from hal_orchestrator.routes.message import _REFUSAL_RX, FALLBACK_REPLIES

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


DENY = ["Adnan", "Joyce", "Bazzy", "adnanakil@gmail.com"]

print("scrub (de-identification before global plane):")
s = scrub("Adnan asked about Bazzy's nap at +12017570419", DENY)
check("names scrubbed", "Adnan" not in s and "Bazzy" not in s, s)
check("phone scrubbed", "2017570419" not in s, s)
check("structure kept", "asked about" in s and "nap" in s, s)
s2 = scrub("email me at adnanakil@gmail.com please", DENY)
check("email scrubbed", "gmail" not in s2, s2)
check("case-insensitive", "joyce" not in scrub("joyce logged a feed", DENY).lower())

print("lint (global publish gate):")
check("rejects name", lint_violation("Always check Bazzy's schedule first", DENY) is not None)
check("rejects phone", lint_violation("text +1 646 513 1421 when stuck", DENY) is not None)
check("rejects email", lint_violation("cc adnanakil@gmail.com", DENY) is not None)
check(
    "accepts generic lesson",
    lint_violation(
        "iCloud Note links cannot be opened; ask the user for a screenshot instead",
        DENY,
    )
    is None,
)
check(
    "accepts generic baby guidance",
    lint_violation(
        "When a user reports a past clock time, backdate the event from the "
        "message timestamp rather than logging it as now",
        DENY,
    )
    is None,
)

print("parse_json_block:")
check("plain json", parse_json_block('{"a": 1}') == {"a": 1})
check("fenced json", parse_json_block('```json\n{"a": 1}\n```') == {"a": 1})
check("prose prefix", parse_json_block('Here you go:\n{"a": 1}') == {"a": 1})
check("trailing prose", parse_json_block('{"a": 1}\nHope that helps!') == {"a": 1})
check("garbage -> {}", parse_json_block("no json here") == {})

print("refusal heuristic:")
refusals = [
    "I actually can't book it for you—I can only find the tables",
    "I can't read shared iCloud Notes directly since Apple blocks automated access",
    "I'm unable to access Instagram posts",
    "Sorry, I don't have access to your location",
]
non_refusals = [
    "Logged his nap at 11:34 AM! He had a nice long wake window this morning.",
    "Yes, this is 100% true and backed by decades of developmental psychology!",
    "You can't go wrong with either time slot honestly",
]
for r in refusals:
    check(f"matches: {r[:40]}...", _REFUSAL_RX.search(r) is not None)
for n in non_refusals:
    check(f"ignores: {n[:40]}...", _REFUSAL_RX.search(n) is None)

print("fallback set:")
check("has 5 entries", len(FALLBACK_REPLIES) == 5, str(len(FALLBACK_REPLIES)))



# --- overseer health check (pure pieces) ------------------------------------ #
from hal_orchestrator.services.growth import HEALTH_PROMPT, build_health_payload

print("\noverseer health payload:")
rows = [
    ("tool_error", "get_weather: Couldn't find a location matching 'Chelsea, Manhattan'"),
    ("tool_error", "get_weather: Couldn't find a location matching 'Chelsea, Manhattan'"),
    ("tool_error", "get_weather: Couldn't find a location matching 'Fort Greene'"),
    ("model_failure", "gemini_failed"),
    ("stub_tool", "vault"),
]
payload = build_health_payload(rows, {"ok": 90, "gemini_failed": 4}, {
    "failures_by_category": [{"category": "infra_error", "count": 3}],
    "today": {"handled_rate": 0.91},
    "trailing_week": {"handled_rate": 0.93},
})
fr = payload["friction_last_24h"]
check("kinds sorted by volume", fr[0]["kind"] == "tool_error" and fr[0]["count"] == 3)
check("identical details grouped", fr[0]["top_details"][0]["n"] == 2)
check("status counts included", payload["turn_status_counts"]["gemini_failed"] == 4)
check("rates included", payload["handled_rate_today"] == 0.91)
check("prompt demands strict JSON + conservatism",
      "STRICT JSON" in HEALTH_PROMPT and "NO finding for noise" in HEALTH_PROMPT)
check("prompt defines fixable tiers", '"config"' in HEALTH_PROMPT and '"code"' in HEALTH_PROMPT)

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
