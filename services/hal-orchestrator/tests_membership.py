"""Tests for the group membership boundary (2026-07-19):

  1. recall_floor — the pure entitlement rule (epoch + roster → archive floor)
  2. prompt guidance — the membership-boundary rules are in the group block
  3. provenance surface — create_family/ensure_family_member/revoke signatures

Pure-function style — no DB, no network. Run:
    uv run python tests_membership.py
"""

import inspect
import os
import sys
from datetime import datetime, timezone

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.prompts.system import GROUP_PRIVACY_BLOCK, SYSTEM_PROMPT
from hal_orchestrator.services.baby import (
    create_family,
    ensure_family_member,
    revoke_thread_member,
)
from hal_orchestrator.services.membership import recall_floor

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


EPOCH = "2026-07-19T15:00:00+00:00"
GROUP_PROFILE = {
    "member_epoch": EPOCH,
    "epoch_roster": ["+15550001111", "+15550002222"],
}

# --- 1. recall_floor --------------------------------------------------------- #
print("recall_floor:")
check("no profile -> unrestricted", recall_floor(None, "+15550009999") is None)
check("no epoch -> unrestricted", recall_floor({}, "+15550009999") is None)
check(
    "pre-epoch member -> unrestricted (the catch-them-up valve)",
    recall_floor(GROUP_PROFILE, "+15550001111") is None,
)
floor = recall_floor(GROUP_PROFILE, "+15550009999")
check(
    "new member -> floored at the epoch",
    floor == datetime(2026, 7, 19, 15, 0, tzinfo=timezone.utc),
    f"got {floor}",
)
check(
    "ambient (requester None) -> always floored",
    recall_floor(GROUP_PROFILE, None) is not None,
)
check(
    "garbage epoch -> unrestricted, never crashes",
    recall_floor({"member_epoch": "not-a-date"}, "+1555") is None,
)
check(
    "empty roster -> everyone floored",
    recall_floor({"member_epoch": EPOCH, "epoch_roster": []}, "+15550001111")
    is not None,
)

# Multi-epoch per-member floors — the union-roster attack from adversarial
# review: Eve joins at cut 1, speaks, then Carol is added (cut 2). Eve must
# stay floored at HER entry (cut 1) — never unrestricted.
E1 = "2026-07-19T15:00:00+00:00"
E2 = "2026-07-19T18:00:00+00:00"
MULTI = {
    "member_epoch": E2,
    "member_epochs": [
        {"at": E1, "roster": ["+15550001111", "+15550002222"]},
        {"at": E2, "roster": ["+15550001111", "+15550002222", "+15550003333"]},
    ],
    "epoch_roster": ["+15550001111", "+15550002222", "+15550003333"],
}
check(
    "founding member -> unrestricted across epochs",
    recall_floor(MULTI, "+15550001111") is None,
)
eve = recall_floor(MULTI, "+15550003333")
check(
    "UNION ATTACK DEAD: epoch-1 joiner floored at HER entry after a later cut",
    eve == datetime(2026, 7, 19, 15, 0, tzinfo=timezone.utc),
    f"got {eve}",
)
carol = recall_floor(MULTI, "+15550009999")
check(
    "newest joiner floored at the latest epoch",
    carol == datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc),
    f"got {carol}",
)
check(
    "ambient floored at the latest epoch",
    recall_floor(MULTI, None)
    == datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc),
)

# --- 2. prompt guidance ------------------------------------------------------ #
print("\nprompt guidance:")
check(
    "group block states the boundary",
    "MEMBERSHIP BOUNDARY" in GROUP_PRIVACY_BLOCK,
)
check(
    "boundary matches iMessage semantics",
    "newest member joined" in GROUP_PRIVACY_BLOCK,
)
check(
    "the valve is member-permissioned",
    "THEIR ask is the permission" in GROUP_PRIVACY_BLOCK,
)
check(
    "baby log exempt (shared by design)",
    "baby log is unaffected" in GROUP_PRIVACY_BLOCK,
)
check(
    "global privacy block covers removal-revocation",
    "removing someone from the family thread ends their access" in SYSTEM_PROMPT.lower(),
)
check(
    "global privacy block covers the join boundary",
    "never sees what was said before they joined" in SYSTEM_PROMPT,
)

# --- 3. provenance surface --------------------------------------------------- #
print("\nprovenance surface:")
sig = inspect.signature(revoke_thread_member)
check("revoke_thread_member(session, family, silo) exists", len(sig.parameters) == 3)
src_create = inspect.getsource(create_family)
check("create_family records creator provenance", '"creator"' in src_create)
src_ensure = inspect.getsource(ensure_family_member)
check("ensure_family_member records thread provenance", '"thread"' in src_ensure)
src_revoke = inspect.getsource(revoke_thread_member)
check(
    "revocation only touches thread-provenance seats",
    'prov != "thread"' in src_revoke,
)

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all passed")
