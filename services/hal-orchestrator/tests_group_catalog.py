"""Tests for the group-context catalog feature (2026-07-08).

Covers the deterministic, DB-free pieces: format_catalog's rendering/caps,
the recall_history group= refusal strings, and the backfill sender-prefix
regex. Live DB behavior (record_participation, is_member, load_catalog_rows)
is not exercised here — see message.py's own best-effort wrapping for how
failures there degrade instead of breaking a turn.

Run: python3 services/hal-orchestrator/tests_group_catalog.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


# --------------------------------------------------------------------------- #
print("group_catalog.format_catalog:")
from hal_orchestrator.services.group_catalog import (  # noqa: E402
    CATALOG_HEADER,
    CATALOG_INSTRUCTION,
    MAX_BLOCK_CHARS,
    format_catalog,
)

NOW = datetime(2026, 7, 8, 18, 0, tzinfo=timezone.utc)

check("empty rows -> None", format_catalog([], NOW) is None)

row_named = {
    "group_silo": "chat957723300680920907",
    "group_name": "Family",
    "activity": NOW - timedelta(hours=2),
    "summary": "Planning the Mattituck trip for August.",
}
block = format_catalog([row_named], NOW)
check("header present", block is not None and CATALOG_HEADER in block)
check("instruction line present", block is not None and CATALOG_INSTRUCTION in block)
check("group id appears in the line", "chat957723300680920907" in block)
check("group name used over raw id", '"Family"' in block)
check(
    "recall_history(group=...) mentioned",
    "recall_history with group=" in CATALOG_INSTRUCTION,
)

print("group_catalog — long-vs-short summary head by recency:")
# "q" (not "x"/"y") because it doesn't appear anywhere in the fixed template
# text (header/instruction/ids) — an exact count only measures the summary
# head, with no risk of a stray letter elsewhere inflating it.
long_summary = "q" * 500
recent_row = {
    "group_silo": "chatRECENT000000000000",
    "group_name": "Recent Group",
    "activity": NOW - timedelta(hours=1),  # within the 6h "recent" window
    "summary": long_summary,
}
stale_row = {
    "group_silo": "chatSTALE0000000000000",
    "group_name": "Stale Group",
    "activity": NOW - timedelta(hours=20),  # outside the 6h window
    "summary": long_summary,
}
recent_block = format_catalog([recent_row], NOW)
stale_block = format_catalog([stale_row], NOW)
# 400-char head for a group active within 6h.
check("recent (<=6h) group gets a long (400-char) head", recent_block.count("q") == 400,
      detail=str(recent_block.count("q")))
# 150-char head, not the full 400, for a group active >6h ago.
stale_head_len = stale_block.count("q")
check("stale (>6h) group gets the short (150-char) head", stale_head_len == 150, detail=str(stale_head_len))

print("group_catalog — newline stripping in summary heads:")
newline_row = {
    "group_silo": "chatNEWLINE000000000000",
    "group_name": "Newline Group",
    "activity": NOW - timedelta(hours=1),
    "summary": "Line one.\nLine two.\r\nLine three.",
}
nl_block = format_catalog([newline_row], NOW)
nl_line = [ln for ln in nl_block.splitlines() if "Newline Group" in ln][0]
check("no raw newline survives inside the rendered line", "\n" not in nl_line.strip("\n"))
check("words from every line still present", "Line one." in nl_block and "Line three." in nl_block)

print("group_catalog — total block stays under the cap:")
many_rows = [
    {
        "group_silo": f"chatMANY{i:015d}",
        "group_name": f"Group {i}",
        "activity": NOW - timedelta(hours=1, minutes=i),
        "summary": "y" * 500,
    }
    for i in range(10)
]
big_block = format_catalog(many_rows, NOW)
check("capped block respects MAX_BLOCK_CHARS", len(big_block) <= MAX_BLOCK_CHARS + 50,
      detail=str(len(big_block)))
check("capped block still ends with the instruction", big_block.rstrip().endswith(CATALOG_INSTRUCTION))

print("group_catalog — no-name group falls back to a shortened id:")
noname_row = {
    "group_silo": "chat123456789012345678901234",
    "group_name": None,
    "activity": NOW - timedelta(hours=1),
    "summary": "hi",
}
noname_block = format_catalog([noname_row], NOW)
check("shortened id used when no group_name", "chat123456789012345678901234" not in noname_block.split(" (id:")[0])
check("full id still present via the id: field", "chat123456789012345678901234" in noname_block)

# --------------------------------------------------------------------------- #
print("tools/history — group= refusal strings:")
from hal_orchestrator.tools.history import (  # noqa: E402
    GROUP_TO_GROUP_REFUSAL,
    NOT_A_MEMBER_REFUSAL,
)

check("group-to-group refusal mentions group-to-group", "group-to-group" in GROUP_TO_GROUP_REFUSAL.lower())
check("not-a-member refusal is short and clear", "participate" in NOT_A_MEMBER_REFUSAL.lower())

# --------------------------------------------------------------------------- #
print("backfill — sender-prefix regex against sample prefixed messages:")
from backfill_group_members import PARTICIPANT_RX  # noqa: E402

check("single prefixed message", PARTICIPANT_RX.findall("[+12017570419]: hi") == ["+12017570419"])
check(
    "multiple senders in one blob",
    sorted(PARTICIPANT_RX.findall("[+12017570419]: hi\n[+13475551234]: yo")) ==
    sorted(["+12017570419", "+13475551234"]),
)
check("no match on plain text", PARTICIPANT_RX.findall("just talking, no brackets here") == [])
check("timestamp brackets don't false-match (no +digits)", PARTICIPANT_RX.findall("[Wed Jul 8 3:45 PM] hello") == [])
check(
    "same sender repeated collapses via dict, regex still finds both occurrences",
    PARTICIPANT_RX.findall("[+12017570419]: a\n[+12017570419]: b") == ["+12017570419", "+12017570419"],
)

# --------------------------------------------------------------------------- #
print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
