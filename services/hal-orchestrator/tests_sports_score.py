"""Tests for sports_score league resolution — World Cup coverage + the
space->hyphen normalization. Pure mapping logic; no network.

Run: python3 services/hal-orchestrator/tests_sports_score.py
"""

import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.tools.sports_score import LEAGUES

failures = []


def check(name, cond):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name}")


def resolve(league_arg: str):
    """Mirror tool_sports_score's resolution (normalize + lookup)."""
    league = (league_arg or "nba").strip().lower().replace(" ", "-")
    return LEAGUES.get(league) or (league if "/" in league else None)


print("World Cup keys map to the FIFA scoreboard:")
for k in ("worldcup", "world-cup", "fifa-world-cup", "wc", "fifa"):
    check(f"{k!r} -> soccer/fifa.world", LEAGUES.get(k) == "soccer/fifa.world")

print("\nmulti-word input normalizes (space -> hyphen) before lookup:")
check("'world cup' -> soccer/fifa.world", resolve("world cup") == "soccer/fifa.world")
check("'World Cup' (caps) -> soccer/fifa.world", resolve("World Cup") == "soccer/fifa.world")
check("'premier league' -> soccer/eng.1", resolve("premier league") == "soccer/eng.1")

print("\nexisting leagues still resolve; junk doesn't:")
check("'nba' -> basketball/nba", resolve("nba") == "basketball/nba")
check("'epl' -> soccer/eng.1", resolve("epl") == "soccer/eng.1")
check("default (empty) -> nba", resolve("") == "basketball/nba")
check("'cricket' -> None (unknown)", resolve("cricket") is None)
check("raw path 'soccer/fifa.world' passes through", resolve("soccer/fifa.world") == "soccer/fifa.world")

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
