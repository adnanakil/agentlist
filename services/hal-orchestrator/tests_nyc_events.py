"""Focused tests for Ephemera/HAL formatting and query plumbing.

Run: python3 services/hal-orchestrator/tests_nyc_events.py
"""

import asyncio
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.tools.nyc_events import format_event, tool_nyc_events

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


EVENT = {
    "title": "Writing the Story Only You Can Tell",
    "date": "2026-07-13",
    "time": "July 13, 7:00 PM - 9:00 PM",
    "location": "The Center for Fiction, 15 Lafayette Ave, Brooklyn",
    "neighborhood": "Fort Greene",
    "eventType": "workshop",
    "format": "in_person",
    "organizer": "The Center for Fiction",
    "instructor": "Vanessa Walters",
    "price": "$75",
    "registrationRequired": True,
    "registrationStatus": "open",
    "registrationUrl": "https://example.com/register",
    "recurrence": "Weekly Mondays through July 27",
    "sessionCount": 3,
    "calendar": {
        "ready": True,
        "start": "2026-07-13T19:00:00-04:00",
        "end": "2026-07-13T21:00:00-04:00",
        "timezone": "America/New_York",
        "endIsEstimated": False,
    },
}


print("calendar-ready formatting:")
rendered = format_event(EVENT)
check("type + format", "[workshop, in person]" in rendered, rendered)
check(
    "instructor + organizer",
    "with Vanessa Walters · by The Center for Fiction" in rendered,
    rendered,
)
check("price + registration", "$75 · registration open" in rendered, rendered)
check(
    "series metadata",
    "Series: Weekly Mondays through July 27 (3 sessions)" in rendered,
    rendered,
)
check(
    "exact calendar interval",
    "2026-07-13T19:00:00-04:00 → 2026-07-13T21:00:00-04:00" in rendered,
    rendered,
)
check(
    "registration link preferred",
    rendered.rstrip().endswith("https://example.com/register"),
    rendered,
)

estimated = {
    **EVENT,
    "calendar": {**EVENT["calendar"], "endIsEstimated": True},
}
check("estimated end disclosed", "[end estimated]" in format_event(estimated))


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "success": True,
            "events": [EVENT],
            "lastFetched": "2026-07-10T09:00:00Z",
        }


class FakeHTTP:
    def __init__(self):
        self.calls = []

    async def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse()


class Settings:
    ephemera_url = "https://ephemera.example"


class Context:
    settings = Settings()

    def __init__(self):
        self.http_client = FakeHTTP()


async def run_tool_test():
    ctx = Context()
    output = await tool_nyc_events(
        {
            "since": "2026-07-10",
            "until": "2026-07-31",
            "event_type": "class",
            "format": "in_person",
            "calendar_ready": True,
            "limit": 5,
        },
        ctx,
    )
    params = ctx.http_client.calls[0]["params"]
    check("event_type forwarded", params.get("event_type") == "class", params)
    check("format forwarded", params.get("format") == "in_person", params)
    check("calendar_ready forwarded", params.get("calendar_ready") is True, params)
    check("structured result reaches HAL", "Calendar:" in output, output)


asyncio.run(run_tool_test())

if failures:
    print(f"\n{len(failures)} FAILED: {', '.join(failures)}")
    raise SystemExit(1)

print("\nall nyc_events tests passed")
