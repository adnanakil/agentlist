"""Tests for the /admin/test console's pure pieces: the test-namespace guard
(the wall between simulated silos and real users), console auth, the bridge
forwarding gate, and the "test" channel plumbing.
Run: python3 services/hal-orchestrator/tests_testconsole.py
"""
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import HTTPException

import hal_orchestrator.state as state
from hal_orchestrator.routes.testconsole import (
    _MENTION_RX,
    _as_silo,
    _require_test,
    _verify_console_auth,
    CONSOLE_HTML,
    is_test_silo,
)

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


def raises_400(*handles):
    try:
        _require_test(*handles)
        return False
    except HTTPException as e:
        return e.status_code == 400


print("namespace guard:")
check("test phone ok", is_test_silo("+15555550100"))
check("formatted test phone normalizes", _as_silo("+1 (555) 555-0142") == "+15555550142")
check("10-digit test phone normalizes", _as_silo("5555550142") == "+15555550142")
check("test group ok", is_test_silo("chattest1a2b3c"))
check("real phone rejected", raises_400("+12017570419"))
check("real group id rejected", raises_400("chat783794800760957500"))
check("email rejected", raises_400("someone@example.com"))
check("nearby fake range rejected", raises_400("+15555560100"))
check("short suffix rejected", raises_400("+1555555010"))
check("empty/None skipped", not raises_400(None, "", "+15555550100"))
check("mixed real+test rejected", raises_400("+15555550100", "chat783794800760957500"))

print("\nconsole auth (fails closed):")
_orig_admin, _orig_bridge = state.settings.admin_token, state.settings.hal_bridge_secret


def auth_status(authorization="", token=""):
    try:
        _verify_console_auth(authorization=authorization, token=token)
        return 200
    except HTTPException as e:
        return e.status_code


state.settings.admin_token = ""
state.settings.hal_bridge_secret = ""
check("no secret -> 403 even with empty bearer", auth_status("Bearer ", "") == 403)
state.settings.admin_token = "admintok"
state.settings.hal_bridge_secret = "bridgetok"
check("admin token via header", auth_status("Bearer admintok") == 200)
check("admin token via query", auth_status("", "admintok") == 200)
check("bridge secret NOT accepted when admin token set", auth_status("Bearer bridgetok") == 403)
check("wrong token 403", auth_status("Bearer nope", "nope") == 403)
check("header wins over query", auth_status("Bearer admintok", "wrong") == 200)
state.settings.admin_token = ""
check("bridge-secret fallback when no admin token", auth_status("Bearer bridgetok") == 200)
state.settings.admin_token, state.settings.hal_bridge_secret = _orig_admin, _orig_bridge

print("\nbridge forwarding gate:")
check("plain mention", bool(_MENTION_RX.search("hey Hal what's the weather")))
check("mention with punctuation", bool(_MENTION_RX.search("HAL, log 4oz")))
check("embedded letters don't count", not _MENTION_RX.search("she exhaled slowly"))
check("bare baby log doesn't count", not _MENTION_RX.search("4oz bottle at 3pm"))

print("\nchannel plumbing:")
from hal_orchestrator.services.delivery import KNOWN_CHANNELS

check("test channel known to delivery", "test" in KNOWN_CHANNELS)
check("real channels still known", "imessage" in KNOWN_CHANNELS and "whatsapp" in KNOWN_CHANNELS)

from pydantic import ValidationError

from hal_orchestrator.routes.message import MessageRequest

try:
    MessageRequest(phone="+15555550100", text="hi", channel="test")
    accepted = True
except ValidationError:
    accepted = False
check("ingest accepts channel=test", accepted)
try:
    MessageRequest(phone="+15555550100", text="hi", channel="sms")
    rejected = False
except ValidationError:
    rejected = True
check("ingest still rejects unknown channels", rejected)

print("\nconsole page:")
check("page is self-contained html", CONSOLE_HTML.lstrip().startswith("<!doctype html>"))
check("talks to the console api", "/api/admin/test/send" in CONSOLE_HTML
      and "/api/admin/test/outbox" in CONSOLE_HTML)
check("js regex survived string literal (raw string)", r"/\bhal\b/" not in CONSOLE_HTML
      and "\bhal\b" not in CONSOLE_HTML)  # no backspace chars leaked into the page
check("real-number warning shown", "real number" in CONSOLE_HTML)
check("no external resources", "https://" not in CONSOLE_HTML and "http://" not in CONSOLE_HTML)

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all checks passed")
