"""Tests for Google WRITE support (calendar create + gmail draft/send).

What's deterministic — and what breaks silently if it regresses — is (a) the
service layer's request shaping (event body, base64url RFC2822, naive-datetime
timezone anchoring) and its classification of Google's responses (success vs
scope-insufficient vs transient), and (b) the tool layer's safety gates: group
silos refuse writes, `send` is blocked without confirmed=true, and an old
read-only token surfaces a reconnect prompt. All of that is pure/fakeable and
tested here — no network, no DB, no pytest. The real OAuth + live-API path is
exercised against Google separately, not this harness.

Run: python3 services/hal-orchestrator/tests_google_write.py
"""

import asyncio
import base64
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hal_orchestrator.services.google as gsvc  # noqa: E402
import hal_orchestrator.tools.google as tg  # noqa: E402
from hal_orchestrator.tools.registry import ToolContext  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Fakes for the HTTP layer
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json


class FakeClient:
    """Records POSTs and returns whatever `responder(url, json)` yields.

    A responder may raise to simulate a network error.
    """

    def __init__(self, responder):
        self._responder = responder
        self.calls = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._responder(url, json)


def _decode_raw(raw_b64):
    return base64.urlsafe_b64decode(raw_b64.encode()).decode()


# --------------------------------------------------------------------------- #
# Service helpers (pure)
# --------------------------------------------------------------------------- #

print("_rfc2822_base64:")
raw = gsvc._rfc2822_base64("her@x.com", "Lunch?", "Free at noon?", cc="him@x.com")
decoded = _decode_raw(raw)
check("produces a decodable base64url string", isinstance(raw, str) and bool(decoded))
check("has To header", "To: her@x.com" in decoded, decoded)
check("has Subject header", "Subject: Lunch?" in decoded, decoded)
check("has Cc when given", "Cc: him@x.com" in decoded, decoded)
check("carries the body", "Free at noon?" in decoded, decoded)
no_cc = _decode_raw(gsvc._rfc2822_base64("a@x.com", "s", "b"))
check("omits Cc when not given", "Cc:" not in no_cc, no_cc)

print("_scope_insufficient:")
check("403 -> scope", gsvc._scope_insufficient(FakeResponse(403, text="Forbidden")))
check(
    "403 insufficient scopes -> scope",
    gsvc._scope_insufficient(
        FakeResponse(403, text="Request had insufficient authentication scopes.")
    ),
)
check(
    "401 with scope text -> scope",
    gsvc._scope_insufficient(FakeResponse(401, text="insufficient scope")),
)
check("plain 401 -> not scope", not gsvc._scope_insufficient(FakeResponse(401, text="nope")))
check("200 -> not scope", not gsvc._scope_insufficient(FakeResponse(200)))
check("404 -> not scope", not gsvc._scope_insufficient(FakeResponse(404, text="not found")))
check("500 -> not scope", not gsvc._scope_insufficient(FakeResponse(500, text="oops")))

print("_event_time:")
naive = gsvc._event_time("2026-07-02T15:00:00", "America/New_York")
check("naive gets timeZone", naive.get("timeZone") == "America/New_York", naive)
check("naive keeps dateTime", naive.get("dateTime") == "2026-07-02T15:00:00", naive)
offset = gsvc._event_time("2026-07-02T15:00:00-04:00", "America/New_York")
check("offset omits timeZone", "timeZone" not in offset, offset)
zulu = gsvc._event_time("2026-07-02T19:00:00Z", "America/New_York")
check("Z (utc) omits timeZone", "timeZone" not in zulu, zulu)
naive_no_tz = gsvc._event_time("2026-07-02T15:00:00", None)
check("naive without tz name has no timeZone", "timeZone" not in naive_no_tz, naive_no_tz)


# --------------------------------------------------------------------------- #
# Service write functions (fake HTTP)
# --------------------------------------------------------------------------- #

print("create_calendar_event:")


def _cal_ok(url, json):
    return FakeResponse(
        201,
        {"id": "evt1", "summary": json.get("summary"), "start": json.get("start"),
         "htmlLink": "https://cal/evt1"},
    )


client = FakeClient(_cal_ok)
event, err = run(
    gsvc.create_calendar_event(
        client, "tok", "Dentist", "2026-07-02T15:00:00", "2026-07-02T16:00:00",
        location="123 Main St", attendees=["a@x.com", "b@x.com"],
        timezone="America/New_York",
    )
)
check("success returns (event, None)", err is None and event and event["id"] == "evt1", (event, err))
check("returns html_link", event and event.get("html_link") == "https://cal/evt1", event)
body = client.calls[0]["json"]
check("posts summary", body.get("summary") == "Dentist", body)
check("naive start anchored to tz", body["start"].get("timeZone") == "America/New_York", body)
check("attendees mapped to {email}", body.get("attendees") == [{"email": "a@x.com"}, {"email": "b@x.com"}], body)
check("location included", body.get("location") == "123 Main St", body)
check("posts to primary calendar events url", client.calls[0]["url"] == gsvc.CAL_EVENTS_URL)

_, err = run(
    gsvc.create_calendar_event(
        FakeClient(lambda u, j: FakeResponse(403, text="insufficient authentication scopes")),
        "tok", "X", "2026-07-02T15:00:00", "2026-07-02T16:00:00", timezone="America/New_York",
    )
)
check("403 -> WRITE_ERR_SCOPE", err == gsvc.WRITE_ERR_SCOPE, err)

_, err = run(
    gsvc.create_calendar_event(
        FakeClient(lambda u, j: FakeResponse(500, text="server error")),
        "tok", "X", "2026-07-02T15:00:00", "2026-07-02T16:00:00", timezone="America/New_York",
    )
)
check("500 -> WRITE_ERR_HTTP", err == gsvc.WRITE_ERR_HTTP, err)

print("create_gmail_draft:")
client = FakeClient(lambda u, j: FakeResponse(200, {"id": "d1", "message": {"id": "m1"}}))
draft, err = run(gsvc.create_gmail_draft(client, "tok", "a@x.com", "Hi", "body", cc="c@x.com"))
check("draft success (dict, None)", err is None and draft["id"] == "d1", (draft, err))
check("posts to drafts url", client.calls[0]["url"] == gsvc.GMAIL_DRAFTS_URL)
draft_body = client.calls[0]["json"]
check("wraps raw under message", "raw" in draft_body.get("message", {}), draft_body)
check("draft raw carries recipient", "To: a@x.com" in _decode_raw(draft_body["message"]["raw"]))
_, err = run(
    gsvc.create_gmail_draft(
        FakeClient(lambda u, j: FakeResponse(403, text="ACCESS_TOKEN_SCOPE_INSUFFICIENT")),
        "tok", "a@x.com", "Hi", "b",
    )
)
check("draft 403 -> scope", err == gsvc.WRITE_ERR_SCOPE, err)

print("send_gmail:")
client = FakeClient(lambda u, j: FakeResponse(200, {"id": "s1", "threadId": "t1"}))
sent, err = run(gsvc.send_gmail(client, "tok", "a@x.com", "Hi", "body"))
check("send success (dict, None)", err is None and sent["id"] == "s1", (sent, err))
check("posts to send url", client.calls[0]["url"] == gsvc.GMAIL_SEND_URL)
check("send posts top-level raw", "raw" in client.calls[0]["json"], client.calls[0]["json"])
_, err = run(
    gsvc.send_gmail(
        FakeClient(lambda u, j: FakeResponse(403, text="insufficient")),
        "tok", "a@x.com", "Hi", "b",
    )
)
check("send 403 -> scope", err == gsvc.WRITE_ERR_SCOPE, err)


def _boom(url, json):
    raise RuntimeError("network down")


_, err = run(gsvc.send_gmail(FakeClient(_boom), "tok", "a@x.com", "Hi", "b"))
check("send network error -> WRITE_ERR_HTTP", err == gsvc.WRITE_ERR_HTTP, err)


# --------------------------------------------------------------------------- #
# Tool layer (patched auth/profile, fake HTTP)
# --------------------------------------------------------------------------- #

# Patch the connection/profile lookups so the tool layer runs offline. The real
# write functions still execute against the fake client.
_orig = {
    "is_configured": gsvc.is_configured,
    "get_valid_access_token": gsvc.get_valid_access_token,
    "get_profile": tg.get_profile,
}


async def _fake_token(session, settings, client, silo):
    return "tok"


async def _fake_profile(session, phone):
    return {"timezone": "America/New_York"}


gsvc.is_configured = lambda settings: True
gsvc.get_valid_access_token = _fake_token
tg.get_profile = _fake_profile


def _ctx(client, is_group=False):
    return ToolContext(
        phone="+15550001111",
        session=None,
        settings=object(),
        http_client=client,
        is_group=is_group,
    )


print("tool_google_gmail send — confirmation gate:")
client = FakeClient(lambda u, j: FakeResponse(200, {"id": "s1"}))
res = run(
    tg.tool_google_gmail(
        {"action": "send", "to": "a@x.com", "subject": "Hi", "body": "hello"}, _ctx(client)
    )
)
check("no confirmed -> blocked", "STOP" in res and "confirmed=true" in res, res)
check("no confirmed -> nothing sent", client.calls == [], client.calls)

client = FakeClient(lambda u, j: FakeResponse(200, {"id": "s1"}))
res = run(
    tg.tool_google_gmail(
        {"action": "send", "to": "a@x.com", "subject": "Hi", "body": "hello", "confirmed": True},
        _ctx(client),
    )
)
check("confirmed=True -> sent", res.startswith("Sent") and len(client.calls) == 1, (res, client.calls))

client = FakeClient(lambda u, j: FakeResponse(200, {"id": "s1"}))
res = run(
    tg.tool_google_gmail(
        {"action": "send", "to": "a@x.com", "subject": "Hi", "body": "hi", "confirmed": "true"},
        _ctx(client),
    )
)
check("confirmed='true' string -> sent", res.startswith("Sent"), res)

res = run(
    tg.tool_google_gmail(
        {"action": "send", "to": "", "body": "", "confirmed": True}, _ctx(FakeClient(lambda u, j: None))
    )
)
check("send missing fields -> error", res.startswith("Error"), res)

print("tool_google_gmail create_draft:")
client = FakeClient(lambda u, j: FakeResponse(200, {"id": "d1", "message": {"id": "m1"}}))
res = run(
    tg.tool_google_gmail(
        {"action": "create_draft", "to": "a@x.com", "subject": "Hi", "body": "b"}, _ctx(client)
    )
)
check("draft -> saved, not sent", "Draft saved" in res and "nothing was sent" in res.lower(), res)

client = FakeClient(lambda u, j: FakeResponse(403, text="insufficient scopes"))
res = run(
    tg.tool_google_gmail(
        {"action": "create_draft", "to": "a@x.com", "subject": "Hi", "body": "b"}, _ctx(client)
    )
)
check("draft on old token -> reconnect prompt", res == tg._RECONNECT_FOR_WRITE, res)

print("tool_google_calendar create_event:")
client = FakeClient(_cal_ok)
res = run(
    tg.tool_google_calendar(
        {"action": "create_event", "summary": "Dentist", "start": "2026-07-02T15:00:00"},
        _ctx(client),
    )
)
check("create_event -> created", res.startswith("Created calendar event 'Dentist'"), res)
check("end defaults to +1h", client.calls[0]["json"]["end"]["dateTime"] == "2026-07-02T16:00:00", client.calls[0]["json"])
check("tz passed from profile", client.calls[0]["json"]["start"].get("timeZone") == "America/New_York", client.calls[0]["json"])

res = run(tg.tool_google_calendar({"action": "create_event", "start": "2026-07-02T15:00:00"}, _ctx(FakeClient(_cal_ok))))
check("create_event missing summary -> error", res.startswith("Error"), res)

client = FakeClient(lambda u, j: FakeResponse(403, text="insufficient authentication scopes"))
res = run(
    tg.tool_google_calendar(
        {"action": "create_event", "summary": "X", "start": "2026-07-02T15:00:00"}, _ctx(client)
    )
)
check("create_event on old token -> reconnect prompt", res == tg._RECONNECT_FOR_WRITE, res)

print("group silos refuse writes:")
gclient = FakeClient(lambda u, j: FakeResponse(200, {"id": "x"}))
for action_args in (
    {"action": "create_event", "summary": "X", "start": "2026-07-02T15:00:00"},
):
    res = run(tg.tool_google_calendar(action_args, _ctx(gclient, is_group=True)))
    check("group create_event refused", res == tg._GROUP_REFUSAL and gclient.calls == [], res)
res = run(
    tg.tool_google_gmail(
        {"action": "send", "to": "a@x.com", "body": "b", "confirmed": True},
        _ctx(gclient, is_group=True),
    )
)
check("group send refused", res == tg._GROUP_REFUSAL and gclient.calls == [], res)
res = run(
    tg.tool_google_gmail(
        {"action": "create_draft", "to": "a@x.com", "body": "b"}, _ctx(gclient, is_group=True)
    )
)
check("group create_draft refused", res == tg._GROUP_REFUSAL and gclient.calls == [], res)

# restore patched functions
gsvc.is_configured = _orig["is_configured"]
gsvc.get_valid_access_token = _orig["get_valid_access_token"]
tg.get_profile = _orig["get_profile"]

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
