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
    annotate_seen,
    delivery_directive,
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
    asyncio.run(cron_tool.tool_schedule(
        {"action": "create", "prompt": "morning brief", "due_time": "2026-07-02T08:00:00"},
        ctx,
    ))
    due = _captured["next_run_at"]
    check("naive 8am stored as 8am PDT (15:00 UTC)",
          due.utcoffset().total_seconds() == 0 and due.hour == 15,
          f"got {due.isoformat()}")
finally:
    cron_tool.create_cron = _orig_create
    profiles_mod.get_profile = _orig_get_profile

# --------------------------------------------------------------------------- #
print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
