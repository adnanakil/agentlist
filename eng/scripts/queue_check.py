"""Cheap no-LLM gate for the eng team. Decides whether a cycle is worth running.

Exit 10 = supervisor should launch a full /eng-cycle now; 0 = keep sleeping.

Queue-driven, unlike growth's clock-driven watchdog: an idle queue costs
nothing. A cycle is due when there is at least one `status: open` ticket AND
MIN_GAP_MINUTES have passed since the last cycle — the gap keeps a ticket the
team cannot finish (or keeps failing on) from respawning a cycle every tick.

`--list` prints the parsed queue and exits 0; used by the cycle itself and by
humans who want to know what is pending.
"""

from __future__ import annotations

import pathlib
import re
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
QUEUE = REPO / "eng/queue"
STATE = REPO / "eng/state"
LAST_CYCLE = STATE / "last_cycle"

MIN_GAP_MINUTES = 20
ACTIONABLE = {"open"}
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}

_FIELD_RX = re.compile(r"^-\s*(id|from|status|priority|blast|opened|experiment):\s*(.*?)\s*$")


def parse_ticket(path: pathlib.Path) -> dict | None:
    """Header fields of one ticket, or None if it has no parseable id."""
    fields: dict[str, str] = {}
    for line in path.read_text(errors="replace").splitlines():
        m = _FIELD_RX.match(line)
        if m:
            fields[m.group(1)] = m.group(2)
        elif line.startswith("## "):
            break  # header is above the first section
    if "id" not in fields:
        return None
    fields["path"] = str(path.relative_to(REPO))
    fields.setdefault("status", "open")
    fields.setdefault("priority", "P2")
    return fields


def load_queue() -> list[dict]:
    if not QUEUE.exists():
        return []
    tickets = [
        t
        for p in sorted(QUEUE.glob("ENG-*.md"))
        if (t := parse_ticket(p)) is not None
    ]
    tickets.sort(key=lambda t: (PRIORITY_ORDER.get(t["priority"], 9), t["id"]))
    return tickets


def main() -> int:
    tickets = load_queue()
    actionable = [t for t in tickets if t["status"] in ACTIONABLE]
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")

    if "--list" in sys.argv:
        if not tickets:
            print("queue is empty")
            return 0
        for t in tickets:
            flag = "*" if t["status"] in ACTIONABLE else " "
            print(
                f"{flag} {t['id']:<8} {t['priority']:<3} {t['status']:<11} "
                f"blast={t.get('blast', 'unset'):<6} from={t.get('from', '?'):<7} {t['path']}"
            )
        print(f"\n{len(actionable)} actionable of {len(tickets)}")
        return 0

    last = float(LAST_CYCLE.read_text().strip()) if LAST_CYCLE.exists() else 0.0
    mins_since = (time.time() - last) / 60
    print(
        f"[{stamp}] eng queue_check: actionable={len(actionable)} "
        f"total={len(tickets)} mins_since_cycle={mins_since:.0f}"
    )
    if not actionable:
        return 0
    if mins_since < MIN_GAP_MINUTES:
        print(f"[{stamp}] eng queue_check: holding ({MIN_GAP_MINUTES}m gap not met)")
        return 0
    top = actionable[0]
    print(f"[{stamp}] eng queue_check: cycle due -> {top['id']} ({top['priority']})")
    return 10


if __name__ == "__main__":
    sys.exit(main())
