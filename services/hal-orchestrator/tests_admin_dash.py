"""Tests for the /admin dashboard's pure pieces (renderer + relative time).
Run: python3 services/hal-orchestrator/tests_admin_dash.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.routes.admin import _rel_time, render_dashboard

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


now = datetime.now(timezone.utc)
print("relative time:")
check("now", _rel_time(now, now) == "now")
check("minutes", _rel_time(now - timedelta(minutes=7), now) == "7m")
check("hours", _rel_time(now - timedelta(hours=3), now) == "3h")
check("days", _rel_time(now - timedelta(days=2), now) == "2d")
check("none -> dash", _rel_time(None, now) == "—")

print("\nrenderer:")
rows = [
    {"silo": "+15551234567", "label": "Adnan", "is_group": False,
     "total_msgs": 1234, "user_msgs": 600, "hal_msgs": 634,
     "window_msgs": 78, "msgs_24h": 41, "last_age": "5m"},
    {"silo": "chat9<script>", "label": "Group chat", "is_group": True,
     "total_msgs": 88, "user_msgs": 70, "hal_msgs": 18,
     "window_msgs": 20, "msgs_24h": 0, "last_age": "3d"},
]
totals = {"conversations": 2, "total messages": "1,322"}
h = render_dashboard(rows, totals, "Wed Jul 1, 9:00 PM EDT")
check("both rows rendered", "Adnan" in h and "Group chat" in h)
check("group marked", "👥" in h)
check("counts formatted", "1,234" in h and "600 / 634" in h)
check("totals cards", "conversations" in h and "1,322" in h)
check("silo shown", "+15551234567" in h)
check("html-escaped silo (no injection)", "<script>" not in h and "&lt;script&gt;" in h)
check("auto-refresh set", 'http-equiv="refresh"' in h)



# --- landing page ("/", texthal.com) — pure renderer ------------------------ #
from hal_orchestrator.routes.landing import _pretty_number, render_landing

print("\nlanding page:")
check("number pretty-printed", _pretty_number("+16505551234") == "(650) 555-1234")
check("10-digit input ok", _pretty_number("6505551234") == "(650) 555-1234")
check("weird input passes through", _pretty_number("hal") == "hal")
h = render_landing("+16505551234")
check("sms link present", 'href="sms:+16505551234' in h)
check("pretty number shown", "(650) 555-1234" in h)
check("one-liner present", "HAL — the baby log that lives in your group chat" in h)
h2 = render_landing("")
check("no number -> coming soon (no sms link)", "coming soon" in h2 and "sms:" not in h2)

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
