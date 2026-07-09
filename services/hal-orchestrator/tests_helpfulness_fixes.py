"""Tests for the 2026-07-01 helpfulness batch: over-suppression fixes,
identity-keyed heartbeat dedup, claimed-action enforcement, honest web_search
failures, contact-name resolution, cron user-local times, auto archive recall
gating. Pure logic + fakes; no network/db.

Run: python3 services/hal-orchestrator/tests_helpfulness_fixes.py
"""

import asyncio
import os
import sys
from types import SimpleNamespace

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
print("over-suppression fixes (message.py):")
from hal_orchestrator.routes.message import (
    _contains_quiet_sentinel,
    _is_rehash_heartbeat,
    _PAST_REF_RX,
    _unbacked_action_claims,
)

long_alert = (
    "Rain starts around 3pm — if you're planning the stroller walk, get it in "
    "before then. Also your package from Amazon was just delivered …"
)
check("long real alert ending in ellipsis NOT suppressed",
      not _contains_quiet_sentinel(long_alert))
check("short 'nothing to flag ...' still suppressed",
      _contains_quiet_sentinel("Nothing worth flagging right now ..."))
check("'No new flights — 5pm cancelled' is NOT a rehash",
      not _is_rehash_heartbeat("No new flights — your 5pm to SFO was CANCELLED."))
check("'nothing new here' still a rehash",
      _is_rehash_heartbeat("Nothing new since my last check."))
check("'already flagged the projector' still a rehash",
      _is_rehash_heartbeat("Already flagged the projector delivery earlier."))
check("heartbeat 'Got it, noted...' ack is suppressed",
      _is_rehash_heartbeat("Got it, noted that it's topped up and resolved! 👍"))
check("heartbeat 'Noted — won't bring it up again' suppressed",
      _is_rehash_heartbeat("Noted, I won't bring it up again."))
check("real 'Heads up' alert not caught by ack leads",
      not _is_rehash_heartbeat("Heads up: your API access was disabled — out of credits."))

# --------------------------------------------------------------------------- #
print("\nclaimed-action detection:")
check("reminder claim w/o tool flagged",
      _unbacked_action_claims("Done — I've set a reminder for 5pm.", set()) == ["set_reminder"])
check("reminder claim WITH tool not flagged",
      _unbacked_action_claims("Done — I've set a reminder for 5pm.", {"set_reminder"}) == [])
check("'I'll remind you' counts as a claim",
      "set_reminder" in _unbacked_action_claims("I'll remind you at 5.", set()))
check("baby log claim w/o baby tool flagged",
      _unbacked_action_claims("Logged the 2:30 feed. Next nap ~4.", set()) == ["baby log"])
check("baby log claim satisfied by baby tool",
      _unbacked_action_claims("Logged the 2:30 feed.", {"baby"}) == [])
check("watch promise w/o watch flagged",
      "watch" in _unbacked_action_claims("I'll let you know the moment they take the lead.", set()))
check("plain answer not flagged",
      _unbacked_action_claims("The Knicks won 112-104 last night.", set()) == [])
check("texted claim needs send_message",
      "send_message" in _unbacked_action_claims("Sent the message to Seth.", set()))
check("texted claim satisfied by delegate",
      _unbacked_action_claims("Sent the message to Seth.", {"delegate"}) == [])

# --------------------------------------------------------------------------- #
print("\nauto archive recall gating:")
for s, expected in [
    ("what was that ramen place you recommended?", True),
    ("remember when we talked about the Berlin trip?", True),
    ("what did I say about the contractor last week", True),
    ("set a reminder for 5pm", False),
    ("how's the weather tomorrow", False),
]:
    check(f"{s[:44]!r} -> {'recalls' if expected else 'skips'}",
          bool(_PAST_REF_RX.search(s)) == expected)

# --------------------------------------------------------------------------- #
print("\nheartbeat identity dedup:")
from datetime import datetime, timedelta, timezone

from hal_orchestrator.services.heartbeat import (
    SEEN_MARK,
    _prune_seen,
    _without_snippet,
    annotate_seen,
    delivery_directive,
    directive_bypass,
    ids_covered_by_alert,
)

gathered = (
    "Recent unread email:\n"
    "- [id: abc123] from Amazon — Delivered: your projector was left at the front door\n"
    "- [id: def456] from Sarah Chen — Re: dinner Saturday?\n"
    "- [id: ghi789] from Substack — This week in AI"
)
annotated = annotate_seen(gathered, {"abc123": "2026-07-01T10:00:00+00:00"})
check("seen line annotated", SEEN_MARK in annotated.splitlines()[1])
check("unseen lines untouched",
      SEEN_MARK not in annotated.splitlines()[2] and SEEN_MARK not in annotated.splitlines()[3])
check("directive fires on fresh delivery", delivery_directive(gathered) != "")
check("directive does NOT fire when the delivery line is already seen",
      delivery_directive(annotated) == "")

reply = "Heads up — your projector was delivered, it's at the front door."
covered = ids_covered_by_alert(gathered, reply, directive_fired=True)
check("alert covers the delivery id", "abc123" in covered)
check("alert does not cover the unmentioned newsletter", "ghi789" not in covered)
reply2 = "Sarah replied about dinner Saturday — want me to check Resy?"
covered2 = ids_covered_by_alert(gathered, reply2, directive_fired=False)
check("reply-overlap covers Sarah's email", "def456" in covered2)
check("reply-overlap leaves the delivery for a future alert", "abc123" not in covered2)
check("already-annotated lines never re-covered",
      ids_covered_by_alert(annotated, reply, True) == [])

now = datetime.now(timezone.utc)
seen = {
    "fresh": now.isoformat(),
    "stale": (now - timedelta(days=10)).isoformat(),
    "garbage": "not-a-date",
}
pruned = _prune_seen(seen, now)
check("prune keeps fresh, drops stale+garbage", set(pruned) == {"fresh"})

# --------------------------------------------------------------------------- #
print("\nheartbeat: subject-only delivery scan (2026-07-09 dup-brief fix):")

newsletter_gathered = (
    "Recent unread email:\n"
    "- [id: news001] from The Daily Scoop — Your weekly roundup"
    "  (Fresh headlines delivered straight to your inbox every morning!)"
)
check("newsletter SNIPPET saying 'delivered' does NOT fire the directive",
      delivery_directive(newsletter_gathered) == "")

subject_delivery_gathered = (
    "Recent unread email:\n"
    "- [id: pkg001] from Amazon — Delivered: your package"
    "  (Thanks for shopping with us — see other deals inside)"
)
check("SUBJECT saying 'Delivered: your package' fires the directive",
      delivery_directive(subject_delivery_gathered) != "")

subject_delivery_gathered2 = (
    "Recent unread email:\n"
    "- [id: pkg002] from UPS — Your package was delivered"
    "  (Track future shipments in the UPS app)"
)
check("SUBJECT 'Your package was delivered' fires the directive",
      delivery_directive(subject_delivery_gathered2) != "")

subject_delivery_seen = annotate_seen(
    subject_delivery_gathered, {"pkg001": "2026-07-01T10:00:00+00:00"}
)
check("subject-delivery line already SEEN_MARK'd -> directive does NOT fire",
      delivery_directive(subject_delivery_seen) == "")

check("_without_snippet strips the trailing parenthetical",
      _without_snippet(
          "- [id: x] from A — Subject here  (some snippet (with parens))"
      ) == "- [id: x] from A — Subject here")
check("_without_snippet no-ops a line with no snippet",
      _without_snippet("- [id: x] from A — Subject here") == "- [id: x] from A — Subject here")

print("\nheartbeat: directive_bypass requires delivery-worded reply:")
check("directive + delivery-worded reply -> bypass True",
      directive_bypass("‼️ some directive", "Heads up — your package was delivered!"))
check("directive + generic weather/plans reply -> bypass False",
      not directive_bypass("‼️ some directive", "Looks like rain around 3pm, bring an umbrella."))
check("no directive -> bypass False even with delivery-worded reply",
      not directive_bypass("", "Your package was delivered."))

# --------------------------------------------------------------------------- #
print("\nhonest web_search failures:")
import hal_orchestrator.tools.web_search as ws


class _FakeResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text

    def json(self):
        return {}


class _FakeHttp:
    def __init__(self, resp):
        self._resp = resp
        self.posts = 0

    async def post(self, *a, **k):
        self.posts += 1
        return self._resp

    async def get(self, *a, **k):
        return self._resp


def _ctx(resp):
    return SimpleNamespace(
        http_client=_FakeHttp(resp),
        settings=SimpleNamespace(brave_search_api_key=""),
    )


r = asyncio.run(ws.tool_web_search({"query": "x"}, _ctx(_FakeResp(403, "blocked"))))
check("HTTP 403 -> SEARCH UNAVAILABLE (not 'no results')",
      "SEARCH UNAVAILABLE" in r and "No results" not in r)
r = asyncio.run(ws.tool_web_search({"query": "x"}, _ctx(_FakeResp(200, "<html>please verify you are human</html>"))))
check("challenge page -> SEARCH UNAVAILABLE", "SEARCH UNAVAILABLE" in r)
real_empty = '<html><div class="no-results">no result for query</div></html>'
r = asyncio.run(ws.tool_web_search({"query": "x"}, _ctx(_FakeResp(200, real_empty))))
check("genuine empty SERP -> honest no-results", r.startswith("No results found"))

# --------------------------------------------------------------------------- #
print("\ncontact-name resolution (send_message):")
import hal_orchestrator.services.profiles as profiles_mod
import hal_orchestrator.tools.send_message as sm


async def _fake_get_profile(session, phone):
    return {
        "phone": phone,
        "extra_data": {"contacts": {"wife": {"name": "Wife", "phone": "+15551234567"}}},
    }


_orig_get_profile = profiles_mod.get_profile
profiles_mod.get_profile = _fake_get_profile
try:
    ctx = SimpleNamespace(phone="+1000", session=None, side_messages=[])
    r = asyncio.run(sm.tool_send_message({"to": "wife", "text": "omw"}, ctx))
    check("saved name resolves to number",
          "+15551234567" in r and ctx.side_messages[0]["to"] == "+15551234567")
    ctx2 = SimpleNamespace(phone="+1000", session=None, side_messages=[])
    r = asyncio.run(sm.tool_send_message({"to": "randomguy", "text": "yo"}, ctx2))
    check("unknown name refuses + lists saved", "wife" in r and not ctx2.side_messages)
    ctx3 = SimpleNamespace(phone="+1000", session=None, side_messages=[])
    r = asyncio.run(sm.tool_send_message({"to": "+1 (555) 987-6543", "text": "hi"}, ctx3))
    check("raw number passes straight through", ctx3.side_messages[0]["to"] == "+1 (555) 987-6543")
finally:
    profiles_mod.get_profile = _orig_get_profile

# --------------------------------------------------------------------------- #
print("\ncron naive due_time -> user-local:")
import hal_orchestrator.tools.cron as cron_tool


async def _fake_get_profile_la(session, phone):
    return {"phone": phone, "timezone": "America/Los_Angeles", "extra_data": {}}


class _FakeJob:
    id = "j1"


_captured = {}


async def _fake_create_cron(session, **kw):
    _captured.update(kw)
    return _FakeJob()


profiles_mod.get_profile = _fake_get_profile_la
_orig_create = cron_tool.create_cron
cron_tool.create_cron = _fake_create_cron
try:
    ctx = SimpleNamespace(
        phone="+1000", session=None, is_group=False, chat_id=None, sender_phone=None
    )
    # The due_time must stay in the future or tool_schedule's past-due guard
    # rejects it before create_cron runs (a hard-coded 2026-07-02 rotted here).
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    _naive = (datetime.now() + timedelta(days=2)).replace(
        hour=8, minute=0, second=0, microsecond=0
    )
    _expected = _naive.replace(tzinfo=ZoneInfo("America/Los_Angeles")).astimezone(
        timezone.utc
    )
    asyncio.run(cron_tool.tool_schedule(
        {"action": "create", "prompt": "morning brief",
         "due_time": _naive.strftime("%Y-%m-%dT%H:%M:%S")},
        ctx,
    ))
    due = _captured["next_run_at"]
    check("naive 8am stored as 8am LA time (UTC row)",
          due.utcoffset().total_seconds() == 0 and due == _expected,
          f"got {due.isoformat()}")
finally:
    cron_tool.create_cron = _orig_create
    profiles_mod.get_profile = _orig_get_profile

# --------------------------------------------------------------------------- #
print("\ngroup tact gate (unprompted-interjection filter):")
from hal_orchestrator.routes.message import _needs_group_tact_gate, build_tact_prompt

BANTER = "Off my own damn street, I immediately became old angry NYer"
DRAFT = "The absolute worst 🙄 Any idea what they're filming?"
check("unprompted banter interjection -> gated",
      _needs_group_tact_gate(True, True, False, BANTER, DRAFT))
check("'Hal, how long to JFK?' -> NOT gated (addressed)",
      not _needs_group_tact_gate(True, True, False, "Hal, how long to JFK?", "About 40 min"))
check("'halloween party sat' -> still gated (word boundary)",
      _needs_group_tact_gate(True, True, False, "halloween party sat!", DRAFT))
check("message with a link -> NOT gated (TL;DR duty)",
      not _needs_group_tact_gate(True, True, False, "look https://x.com/foo", "📄 TL;DR ..."))
check("sentinel reply -> NOT gated (already silent)",
      not _needs_group_tact_gate(True, True, False, BANTER, "..."))
check("1:1 chat -> never gated",
      not _needs_group_tact_gate(False, False, False, BANTER, DRAFT))
check("non-watched group -> not gated (only @Hal msgs arrive anyway)",
      not _needs_group_tact_gate(True, False, False, BANTER, DRAFT))
check("internal turn -> not gated (heartbeat suppressors own it)",
      not _needs_group_tact_gate(True, True, True, BANTER, DRAFT))

p = build_tact_prompt("member: pic\nmember: they made me move my car", "Adnan", BANTER, DRAFT)
check("tact prompt carries convo, message, and draft",
      "move my car" in p and BANTER in p and DRAFT in p)
check("tact prompt defaults to DROP when in doubt", "When in doubt, DROP" in p)

# --------------------------------------------------------------------------- #
print("\npast-due guards (AM/PM slip protection):")
import hal_orchestrator.tools.reminders as rem_tool
from datetime import datetime as _dt, timedelta as _td, timezone as _tz


async def _fake_create_reminder(session, **kw):
    return {"id": "r1", "text": kw.get("text"), "due_at": str(kw.get("due_at"))}


_orig_cr = rem_tool.create_reminder
rem_tool.create_reminder = _fake_create_reminder
try:
    ctx = SimpleNamespace(phone="+1000", session=None)
    past = (_dt.now(_tz.utc) - _td(hours=12)).isoformat()
    r = asyncio.run(rem_tool.tool_set_reminder(
        {"action": "create", "text": "bottles", "due_time": past}, ctx))
    check("one-shot past due -> error asking recompute",
          r.startswith("Error") and "PAST" in r)
    fut = (_dt.now(_tz.utc) + _td(minutes=20)).isoformat()
    r = asyncio.run(rem_tool.tool_set_reminder(
        {"action": "create", "text": "bottles", "due_time": fut}, ctx))
    check("future due -> created", r.startswith("Reminder set"))
    r = asyncio.run(rem_tool.tool_set_reminder(
        {"action": "create", "text": "vitamins", "due_time": past, "recur": "daily"}, ctx))
    check("recurring past due -> rolled forward, created", r.startswith("Reminder set"))
finally:
    rem_tool.create_reminder = _orig_cr

_captured2 = {}


async def _fake_create_cron2(session, **kw):
    _captured2.update(kw)
    return _FakeJob()


cron_tool.create_cron = _fake_create_cron2
profiles_mod.get_profile = _fake_get_profile_la
try:
    ctx = SimpleNamespace(phone="+1000", session=None, is_group=False,
                          chat_id=None, sender_phone=None)
    past = (_dt.now(_tz.utc) - _td(hours=5)).isoformat()
    r = asyncio.run(cron_tool.tool_schedule(
        {"action": "create", "prompt": "brief", "due_time": past}, ctx))
    check("cron one-shot past -> error", r.startswith("Error") and "PAST" in r)
    r = asyncio.run(cron_tool.tool_schedule(
        {"action": "create", "prompt": "brief", "due_time": past, "recur": "daily"}, ctx))
    check("cron recurring past -> rolled to future",
          not r.startswith("Error") and _captured2["next_run_at"] > _dt.now(_tz.utc))
finally:
    cron_tool.create_cron = _orig_create
    profiles_mod.get_profile = _orig_get_profile

# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
print("\nweather geocode ladder (Nominatim -> Open-Meteo fallback):")
from hal_orchestrator.tools.weather import _geocode


class _GeoResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._p = payload

    def json(self):
        return self._p


class _GeoHttp:
    """Fake http client routing by URL substring."""
    def __init__(self, nominatim, openmeteo):
        self._n, self._o = nominatim, openmeteo
        self.calls = []

    async def get(self, url, **kw):
        self.calls.append(url)
        return self._n if "nominatim" in url else self._o


def _ctx(http):
    return SimpleNamespace(http_client=http)


nom_hit = _GeoResp(200, [{"lat": "40.746", "lon": "-74.002",
                          "display_name": "Chelsea, Manhattan, New York"}])
om_hit = _GeoResp(200, {"results": [{"latitude": 44.0, "longitude": -72.4,
                                     "name": "Chelsea", "admin1": "Vermont"}]})
empty_nom = _GeoResp(200, [])
err_nom = _GeoResp(503, [])

r = asyncio.run(_geocode(_ctx(_GeoHttp(nom_hit, om_hit)), "Chelsea, Manhattan, New York, NY"))
check("nominatim hit wins", r and abs(r[0] - 40.746) < .001 and "Manhattan" in r[2])
r = asyncio.run(_geocode(_ctx(_GeoHttp(empty_nom, om_hit)), "Chelsea"))
check("empty nominatim -> open-meteo fallback", r and abs(r[0] - 44.0) < .001)
r = asyncio.run(_geocode(_ctx(_GeoHttp(err_nom, om_hit)), "Chelsea"))
check("nominatim 5xx -> open-meteo fallback", r and abs(r[0] - 44.0) < .001)
r = asyncio.run(_geocode(_ctx(_GeoHttp(empty_nom, _GeoResp(200, {"results": []}))), "zzzz"))
check("both miss -> None (honest failure)", r is None)

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
