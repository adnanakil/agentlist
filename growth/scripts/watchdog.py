"""Cheap no-LLM health check between full growth cycles.

Runs budget_guard; decides whether a full agent cycle is due.
Exit 10 = supervisor should launch a full /growth-daily cycle now; 0 = keep sleeping.

A full cycle is due when EITHER:
  - CYCLE_HOURS have passed since the last one, or
  - budget_guard clamped or errored (alert) AND at least MIN_GAP_HOURS have passed
    (so a persistent alert, e.g. dead OAuth, doesn't spawn a cycle every tick).
"""
import pathlib
import subprocess
import sys
import time

REPO = pathlib.Path("/Users/adnanakil/Project/agentlist")
STATE = REPO / "growth/state"
LAST_CYCLE = STATE / "last_cycle"
CYCLE_HOURS = 6
MIN_GAP_HOURS = 2

now = time.time()
last = float(LAST_CYCLE.read_text().strip()) if LAST_CYCLE.exists() else 0.0
hours_since = (now - last) / 3600

guard = subprocess.run(
    [sys.executable, str(REPO / "growth/scripts/budget_guard.py")],
    capture_output=True, text=True,
)
alert = guard.returncode != 0
stamp = time.strftime("%Y-%m-%d %H:%M:%S")
print(f"[{stamp}] watchdog: guard_rc={guard.returncode} hours_since_cycle={hours_since:.1f}")
if alert:
    print(guard.stdout.strip())
    print(guard.stderr.strip()[-500:])

if hours_since >= CYCLE_HOURS or (alert and hours_since >= MIN_GAP_HOURS):
    print(f"[{stamp}] watchdog: full cycle due (alert={alert})")
    sys.exit(10)
sys.exit(0)
