"""Tests for the watch feature's pure logic: ESPN parsing, _extract_json, and
the checker's verdict/terminator branches (with a fake session + poll).

Run: python3 services/hal-orchestrator/tests_watch.py
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services import watch as wsvc
from hal_orchestrator.services.watch import _extract_json
from hal_orchestrator.tools.sports_score import tool_sports_score

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


# --------------------------------------------------------------------------- #
# _extract_json
# --------------------------------------------------------------------------- #
print("_extract_json:")
check("plain", _extract_json('{"condition_met": true, "terminal": false}') == {"condition_met": True, "terminal": False})
check("fenced", _extract_json('```json\n{"condition_met": false}\n```') == {"condition_met": False})
check("prose-wrapped", _extract_json('Here:\n{"condition_met": true}\ndone') == {"condition_met": True})
check("garbage -> None", _extract_json("no json") is None)
check("empty -> None", _extract_json("") is None)


# --------------------------------------------------------------------------- #
# sports_score parsing — mock ctx with a fake ESPN payload
# --------------------------------------------------------------------------- #
print("sports_score parsing:")


from zoneinfo import ZoneInfo as _ZI

_ET = _ZI("America/New_York")
# Default games to "today" so they're treated as live; pass days_ago>0 for stale.
_TODAY_ET = datetime.now(_ET)


def espn_event(away, home, away_score, home_score, state, detail, days_ago=0):
    day = _TODAY_ET - timedelta(days=days_ago)
    return {
        "date": day.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": home, "abbreviation": home[:3].upper()}, "score": home_score},
                    {"homeAway": "away", "team": {"displayName": away, "abbreviation": away[:3].upper()}, "score": away_score},
                ]
            }
        ],
        "status": {"type": {"state": state, "shortDetail": detail, "description": detail}},
    }


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class FakeHTTP:
    def __init__(self, payload):
        self._p = payload

    async def get(self, *a, **k):
        return FakeResp(self._p)


class FakeCtx:
    def __init__(self, payload):
        self.http_client = FakeHTTP(payload)


async def run_sports():
    payload = {
        "events": [
            espn_event("New York Knicks", "San Antonio Spurs", "94", "90", "post", "Final"),
            espn_event("Boston Celtics", "Miami Heat", "55", "60", "in", "Q3 4:21"),
            espn_event("Chicago Bulls", "Detroit Pistons", "0", "0", "pre", "7:30 PM ET"),
        ]
    }
    ctx = FakeCtx(payload)

    out = await tool_sports_score({"league": "nba", "team": "Knicks"}, ctx)
    check("team filter → 1 game", out.count("\n") == 0 and "Knicks" in out, out)
    check("final leader: away Knicks up 4", "Knicks lead by 4" in out and "FINAL" in out, out)

    out2 = await tool_sports_score({"league": "nba", "team": "Heat"}, ctx)
    check("in-progress home Heat up 5", "Heat lead by 5" in out2 and "in progress" in out2, out2)

    out3 = await tool_sports_score({"league": "nba", "team": "Bulls"}, ctx)
    check("pre game shows not started", "not started" in out3, out3)

    out4 = await tool_sports_score({"league": "nba"}, ctx)
    check("no team → all 3 today games", out4.count("\n") == 2, out4)

    out5 = await tool_sports_score({"league": "nba", "team": "Lakers"}, ctx)
    check("no match → message", "No NBA game today" in out5, out5)

    out6 = await tool_sports_score({"league": "quidditch"}, ctx)
    check("unknown league", out6.startswith("Unknown league"), out6)

    # The reported bug: a stale Final from a previous day must NOT read as live.
    stale = FakeCtx({"events": [
        espn_event("New York Knicks", "San Antonio Spurs", "94", "90", "post", "Final", days_ago=2),
    ]})
    out7 = await tool_sports_score({"league": "nba"}, stale)
    check("stale game -> 'no games today' (not presented as live)", out7.startswith("No NBA games today"), out7)
    check("stale game -> most-recent result is DATED", "Most recent" in out7 and "beat" in out7, out7)
    check("stale game -> no 'in progress'/'tonight' framing", "in progress" not in out7 and "FINAL" not in out7, out7)


asyncio.run(run_sports())


# --------------------------------------------------------------------------- #
# Checker branches — fake session + monkeypatched _poll
# --------------------------------------------------------------------------- #
print("checker verdict + terminator branches:")


class FakeWatch:
    def __init__(self, **kw):
        self.id = "w1"
        self.phone = "+15551112222"
        self.condition = "Knicks take the lead"
        self.check_prompt = "Knicks take the lead"
        self.notify = "🏀 The Knicks just took the lead!"
        self.is_group = False
        self.chat_id = None
        self.sender_phone = None
        self.poll_every_seconds = 150
        self.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        self.max_polls = 60
        self.polls_done = 0
        self.consecutive_fails = 0
        self.active = True
        self.last_run_at = None
        self.last_observation = None
        self.next_run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        for k, v in kw.items():
            setattr(self, k, v)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.flushed = 0
        self.committed = 0

    async def execute(self, *a, **k):
        return FakeResult(self._rows)

    async def flush(self):
        self.flushed += 1

    async def commit(self):
        self.committed += 1


async def run_checker_with(verdict, watch):
    """Drive _check_and_run once with _poll stubbed to return `verdict`."""
    import hal_orchestrator.state as state

    # Drain the outbox.
    while not state.outbox.empty():
        state.outbox.get_nowait()

    async def fake_get_session():
        yield FakeSession([watch])

    orig_poll = wsvc._poll
    orig_get = wsvc.get_session
    wsvc._poll = lambda *a, **k: _aval(verdict)
    wsvc.get_session = fake_get_session
    try:
        await wsvc._check_and_run(_settings(), None)
    finally:
        wsvc._poll = orig_poll
        wsvc.get_session = orig_get

    fired = None
    if not state.outbox.empty():
        fired = state.outbox.get_nowait()
    return fired


async def _aval(v):
    return v


def _settings():
    class S:
        watch_check_interval_seconds = 60
        watch_max_per_silo = 3
        gemini_watch_model = "x"
    return S()


async def run_checker():
    # condition_met → notify + deactivate
    w = FakeWatch()
    fired = await run_checker_with({"condition_met": True, "observation": "NYK 95-94"}, w)
    check("met → fired to silo", fired is not None and fired["to"] == w.phone, fired)
    check("met → notify text + observation", fired and "Knicks just took the lead" in fired["text"] and "NYK 95-94" in fired["text"], fired)
    check("met → deactivated", w.active is False)

    # terminal → silent deactivate
    w = FakeWatch()
    fired = await run_checker_with({"condition_met": False, "terminal": True}, w)
    check("terminal → silent", fired is None)
    check("terminal → deactivated", w.active is False)

    # miss → reschedule + polls_done++
    w = FakeWatch()
    fired = await run_checker_with({"condition_met": False, "terminal": False, "observation": "still down 2"}, w)
    check("miss → silent", fired is None)
    check("miss → still active", w.active is True)
    check("miss → polls_done incremented", w.polls_done == 1, w.polls_done)
    check("miss → rescheduled forward", w.next_run_at > datetime.now(timezone.utc), w.next_run_at)

    # poll failure (None) → fails++
    w = FakeWatch()
    fired = await run_checker_with(None, w)
    check("None → fails incremented", w.consecutive_fails == 1, w.consecutive_fails)
    check("None → still active (under breaker)", w.active is True)

    # terminators fire BEFORE polling (poll would have said met, but expired)
    w = FakeWatch(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    fired = await run_checker_with({"condition_met": True}, w)
    check("expired → deactivated before poll", w.active is False)
    check("expired → no fire despite met verdict", fired is None)

    w = FakeWatch(consecutive_fails=3)
    fired = await run_checker_with({"condition_met": True}, w)
    check("breaker → deactivated before poll", w.active is False and fired is None)

    w = FakeWatch(polls_done=60, max_polls=60)
    fired = await run_checker_with({"condition_met": True}, w)
    check("max_polls → deactivated before poll", w.active is False and fired is None)


asyncio.run(run_checker())

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
