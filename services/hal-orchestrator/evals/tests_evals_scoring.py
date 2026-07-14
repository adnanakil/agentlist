"""Tests for the eval suite's pure scoring/cost/report logic (no API).

Run: python3 services/hal-orchestrator/evals/tests_evals_scoring.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import judge as J  # noqa: E402
import pricing as P  # noqa: E402
import report as R  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


print("parse_grade:")
g = J.parse_grade('{"grade": "handled", "reason": "did it", "failure_category": null}')
check("clean JSON", g["grade"] == "handled" and g["failure_category"] is None)
g = J.parse_grade(
    'Sure, here is my verdict:\n```json\n{"grade": "failed", '
    '"reason": "hallucinated", "failure_category": "hallucination"}\n``` done'
)
check("fenced + junk around JSON", g["grade"] == "failed")
check("category kept on failure", g["failure_category"] == "hallucination")
g = J.parse_grade(
    '{"grade": "handled", "reason": "x", "failure_category": "hallucination"}'
)
check("category nulled when handled", g["failure_category"] is None)
g = J.parse_grade('{"grade": "partial", "reason": "y", "failure_category": "weird"}')
check("unknown category -> other", g["failure_category"] == "other")
try:
    J.parse_grade('{"grade": "excellent", "reason": "?"}')
    check("bad grade raises", False)
except ValueError:
    check("bad grade raises", True)
try:
    J.parse_grade("no json here at all")
    check("no JSON raises", False)
except ValueError:
    check("no JSON raises", True)
g = J.parse_grade('{"grade": "failed", "reason": "' + "x" * 900 + '", "failure_category": null}')
check("reason truncated to 300", len(g["reason"]) <= 300)

print("cost_of:")
usage = {"input": 1_000_000, "cached": 0, "output": 0}
check("input only", abs(P.cost_of(usage, "gpt-5.6-luna") - 1.00) < 1e-9)
usage = {"input": 0, "cached": 1_000_000, "output": 0}
check("cached at 10%", abs(P.cost_of(usage, "gpt-5.6-luna") - 0.10) < 1e-9)
usage = {"input": 100_000, "cached": 900_000, "output": 50_000, "reasoning": 40_000}
# reasoning is a SUBSET of output — must not be billed again
expected = (100_000 * 1.00 + 900_000 * 0.10 + 50_000 * 6.00) / 1e6
check(
    "reasoning not double-billed",
    abs(P.cost_of(usage, "gpt-5.6-luna") - expected) < 1e-9,
    f"got {P.cost_of(usage, 'gpt-5.6-luna')}, want {expected}",
)
usage = {"input": 0, "cached": 0, "output": 0, "cache_write": 1_000_000}
check("anthropic cache write 1.25x", abs(P.cost_of(usage, "claude-sonnet-5") - 3.75) < 1e-9)
check("missing fields = 0", P.cost_of({}, "claude-haiku-4-5") == 0.0)
check("none fields = 0", P.cost_of({"input": None, "output": None}, "gpt-5.4") == 0.0)
try:
    P.cost_of({"input": 1}, "gpt-99-unknown")
    check("unknown model raises", False)
except KeyError:
    check("unknown model raises", True)
check("sonnet cheaper than opus", P.PRICES["claude-sonnet-5"][0] < P.PRICES["claude-opus-4-8"][0])

print("handled_rate:")
check("basic", R.handled_rate({"handled": 8, "partial": 1, "failed": 1}) == 80.0)
check("na excluded", R.handled_rate({"handled": 1, "na": 99}) == 100.0)
check("empty -> None", R.handled_rate({}) is None)
check("only na -> None", R.handled_rate({"na": 5}) is None)

print("aggregate:")
records = [
    {
        "scenario_id": "s1", "category": "weather", "model": "m1",
        "assertions": {"passed": True, "failures": []},
        "usage": {"input": 1_000_000, "cached": 0, "output": 0},
        "latency_ms": 1000,
    },
    {
        "scenario_id": "s2", "category": "baby", "model": "m1",
        "assertions": {"passed": False, "failures": ["missed tool"]},
        "usage": {"input": 1_000_000, "cached": 0, "output": 0},
        "latency_ms": 3000,
    },
    {"scenario_id": "s1", "category": "weather", "model": "m2"},
]
grades = {
    "s1::m1": {"grade": "handled", "reason": ""},
    "s2::m1": {"grade": "failed", "reason": "missed", "failure_category": "missed_tool"},
    # s1::m2 deliberately ungraded -> na
}
# m1 uses a real priced model name for the cost path
for r in records:
    r["model"] = "gpt-5.4-mini" if r["model"] == "m1" else "unpriced-model"
grades = {
    "s1::gpt-5.4-mini": grades["s1::m1"],
    "s2::gpt-5.4-mini": grades["s2::m1"],
}
agg = R.aggregate(records, grades)
m1 = agg["gpt-5.4-mini"]
check("m1 rate 50", m1["rate"] == 50.0)
check("m1 asserts 1/2", m1["assertions_passed"] == 1 and m1["assertions_total"] == 2)
check("m1 costs collected", len(m1["costs"]) == 2 and abs(m1["costs"][0] - 0.75) < 1e-9)
check("m1 failure recorded", m1["failures"][0]["scenario_id"] == "s2")
m2 = agg["unpriced-model"]
check("ungraded -> na", m2["counts"].get("na") == 1 and m2["rate"] is None)
check("unpriced model skips cost", m2["costs"] == [])

print("recommend:")
agg2 = {
    "expensive": {"rate": 90.0, "cat_counts": {}},
    "cheap": {"rate": 88.0, "cat_counts": {}},
    "bad-cheap": {"rate": 60.0, "cat_counts": {}},
}
rec = R.recommend(agg2, {"expensive": 0.10, "cheap": 0.01, "bad-cheap": 0.001})
check("picks cheap within 3 points", rec["pick"] == "cheap")
check("best model tracked", rec["best_model"] == "expensive")
rec = R.recommend(agg2, {"expensive": 0.10, "bad-cheap": 0.001})
check("ineligible cheap skipped", rec["pick"] == "expensive")
check("no data -> None", R.recommend({}, {}) is None)

print("weak_categories:")
agg3 = {
    "best": {"cat_counts": {"weather": {"handled": 10}, "baby": {"handled": 10}}},
    "cheap": {
        "cat_counts": {
            "weather": {"handled": 9, "failed": 1},
            "baby": {"handled": 5, "failed": 5},
        }
    },
}
weak = R.weak_categories(agg3, "cheap", "best")
check("only big gaps flagged", [w[0] for w in weak] == ["baby"])

print("render smoke:")
md = R.render(records, grades, turns_per_day=100.0)
check("has overall table", "## Overall" in md and "gpt-5.4-mini" in md)
check("has projection", "$/month" in md)
md2 = R.render(records, grades, turns_per_day=None)
check("projection skipped without volume", "Skipped" in md2)

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("all checks passed")
