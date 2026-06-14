"""Tests for the group→personal observation valve's pure logic: enricher
output splitting, participant extraction (the membership guard's input).

Run: python3 services/hal-orchestrator/tests_group_observations.py
"""

import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services.group_observations import extract_participants
from hal_orchestrator.services.profile_enricher import split_profile_and_observations

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


print("split_profile_and_observations:")
out = """# Family Chat
Purpose: baby logistics.

===OBSERVATIONS===
[{"handle": "+12017570419", "observation": "Planning a Mattituck trip this weekend"}]"""
profile, obs = split_profile_and_observations(out)
check("profile kept", profile.startswith("# Family Chat") and "OBSERVATIONS" not in profile, profile)
check("obs parsed", len(obs) == 1 and obs[0]["handle"] == "+12017570419", obs)

profile, obs = split_profile_and_observations("# Just a profile, no marker")
check("no marker -> profile only", profile == "# Just a profile, no marker" and obs == [])

profile, obs = split_profile_and_observations("# P\n===OBSERVATIONS===\n[]")
check("empty array", profile == "# P" and obs == [])

profile, obs = split_profile_and_observations("# P\n===OBSERVATIONS===\nnot json at all")
check("garbage obs -> profile survives", profile == "# P" and obs == [])

fenced = '# P\n===OBSERVATIONS===\n```json\n[{"handle": "+15555550100", "observation": "x"}]\n```'
profile, obs = split_profile_and_observations(fenced)
check("fenced json", len(obs) == 1, obs)

trailing = '# P\n===OBSERVATIONS===\n[{"handle": "+15555550100", "observation": "x"}]\nHope that helps!'
profile, obs = split_profile_and_observations(trailing)
check("trailing prose ignored", len(obs) == 1, obs)

print("extract_participants (membership guard input):")
transcript = """user: [Thu Jun 12 8:45 AM] [+12017570419]: Bazzy woke up at 745
model: Logged!
user: [Thu Jun 12 9:02 AM] [+16508239042]: Correction, he ate at 630
user: [Thu Jun 12 9:10 AM] [+12017570419]: Can I make the gym?"""
p = extract_participants(transcript)
check("both senders found", p == {"+12017570419", "+16508239042"}, p)
check("empty transcript", extract_participants("") == set())
check(
    "no false hits on times/ids",
    extract_participants("user: meet at [5pm] in room [12]") == set(),
)

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all passed")
