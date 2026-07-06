"""Tests for the reliability batch: weather provider failover + last-known-good
cache (hal_orchestrator.tools.weather), and the cron slash-command blank-reply
retry (hal_orchestrator.services.cron).

The July 1–3 weather outage was the FORECAST layer (single Open-Meteo call, no
ladder — geocoding already had Nominatim → Open-Meteo). What's deterministic
and breaks silently if it regresses: the provider-ladder selection, the
stale-cache TTL + labeling, the met.no formatter (unit conversion, day
bucketing), and that the Open-Meteo happy-path format is byte-identical to the
legacy output. Live HTTP against the providers is not exercised here.

The cron side: gemini_failed blanked /morning-brief twice (06-16, 06-18). The
retry decision predicate is pure; the _run_job retry flow runs against a fake
/api/message with the retry delay zeroed.

Run: python3 services/hal-orchestrator/tests_reliability.py
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.tools.weather import (  # noqa: E402
    _c_to_f,
    _cache_get,
    _cache_put,
    _forecast_with_failover,
    _format_met_no,
    _format_open_meteo,
    _last_good,
    _met_symbol,
    _ms_to_mph,
    _rain_windows,
    _stale_wrap,
)

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


ET = ZoneInfo("America/New_York")

# --------------------------------------------------------------------------- #
print("provider ladder — first success wins, errors fall through:")

calls = []


def _provider(name, result=None, exc=None):
    async def fetch(ctx, lat, lon, place, days, tz):
        calls.append(name)
        if exc is not None:
            raise exc
        return result

    return (name, fetch)


calls.clear()
out = asyncio.run(_forecast_with_failover(
    None, 40.7, -74.0, "NYC", 3, ET,
    providers=(_provider("a", result="A"), _provider("b", result="B")),
))
check("primary healthy -> primary answer", out == "A", f"got {out!r}")
check("primary healthy -> fallback never called", calls == ["a"], f"got {calls}")

calls.clear()
out = asyncio.run(_forecast_with_failover(
    None, 40.7, -74.0, "NYC", 3, ET,
    providers=(_provider("a", exc=TimeoutError("down")), _provider("b", result="B")),
))
check("primary error -> fallback answer", out == "B", f"got {out!r}")
check("primary error -> both tried in order", calls == ["a", "b"], f"got {calls}")

calls.clear()
try:
    asyncio.run(_forecast_with_failover(
        None, 40.7, -74.0, "NYC", 3, ET,
        providers=(_provider("a", exc=TimeoutError("down")),
                   _provider("b", exc=ValueError("also down"))),
    ))
    check("all providers fail -> raises", False, "no exception")
except ValueError:
    check("all providers fail -> raises (last error)", True)
except Exception as exc:
    check("all providers fail -> raises (last error)", False, f"got {type(exc)}")

# --------------------------------------------------------------------------- #
print("\nlast-known-good cache — TTL + key normalization:")

_last_good.clear()
t0 = datetime(2026, 7, 6, 14, 0, tzinfo=timezone.utc)
_cache_put("Brooklyn, NY", "Weather for Brooklyn:\nNow: 75°F", t0)

hit = _cache_get("Brooklyn, NY", t0 + timedelta(minutes=29))
check("29 min old -> served", hit is not None and hit[0].startswith("Weather for"))
check("fetch time preserved", hit is not None and hit[1] == t0)
check("31 min old -> expired", _cache_get("Brooklyn, NY", t0 + timedelta(minutes=31)) is None)
check("case/whitespace-insensitive key",
      _cache_get("  brooklyn,   ny ", t0 + timedelta(minutes=5)) is not None)
check("different location -> miss", _cache_get("Chelsea, VT", t0) is None)

# --------------------------------------------------------------------------- #
print("\nstale labeling — 'as of HH:MM' in the user's tz:")

# 14:35 UTC == 10:35 AM ET
fetched = datetime(2026, 7, 6, 14, 35, tzinfo=timezone.utc)
s = _stale_wrap("Weather for Brooklyn:\nNow: 75°F", fetched, ET)
check("labeled STALE", s.startswith("[STALE"))
check("as-of clock in user tz", "as of 10:35 AM" in s, f"got {s.splitlines()[0]}")
check("original reading kept intact", s.endswith("Weather for Brooklyn:\nNow: 75°F"))

s = _stale_wrap("x", datetime(2026, 7, 6, 17, 5, tzinfo=timezone.utc), ET)
check("PM + zero-padded minutes", "as of 1:05 PM" in s, f"got {s.splitlines()[0]}")

# --------------------------------------------------------------------------- #
print("\nOpen-Meteo happy-path format — unchanged from legacy:")

om_data = {
    "current": {
        "temperature_2m": 74.6, "apparent_temperature": 77.2,
        "weather_code": 2, "wind_speed_10m": 8.4,
    },
    "daily": {
        "time": ["2026-07-06", "2026-07-07"],
        "weather_code": [2, 61],
        "temperature_2m_max": [82.0, 79.0],
        "temperature_2m_min": [68.0, 66.0],
        "precipitation_probability_max": [20, 65],
    },
    "hourly": {
        "time": [f"2026-07-06T{h:02d}:00" for h in range(24)],
        "precipitation_probability": [0] * 14 + [55, 70, 60] + [0] * 7,
        "precipitation": [0.0] * 24,
    },
}
out = _format_open_meteo(om_data, "Brooklyn, New York")
expected = (
    "Weather for Brooklyn, New York:\n"
    "Now: 75°F (feels 77°F), partly cloudy, wind 8 mph.\n"
    "Today: partly cloudy, 68–82°F, 20% chance precip (daily max).\n"
    "Tomorrow: light rain, 66–79°F, 65% chance precip (daily max).\n"
    "\n"
    "Rain timing (reason from THESE for a plan, not the daily %): "
    "Mon 2pm–Mon 5pm (~70%) — otherwise dry."
)
check("byte-identical to legacy format", out == expected,
      f"\n--- got ---\n{out}\n--- want ---\n{expected}")

for bad in ({}, {"current": {"temperature_2m": 70}}, {"daily": {"time": []}}):
    try:
        _format_open_meteo(bad, "X")
        check(f"degraded payload {bad!r} raises (drives failover)", False, "no exception")
    except ValueError:
        check(f"degraded payload raises (drives failover): {list(bad.keys())}", True)

# --------------------------------------------------------------------------- #
print("\nrain windows — % labels with probabilities, mm/h without (met.no):")

r = _rain_windows({
    "time": [f"2026-07-06T{h:02d}:00" for h in range(6)],
    "precipitation_probability": [None] * 6,
    "precipitation": [0.0, 0.0, 0.5, 1.2, 0.0, 0.0],
})
check("amount-only wet hours found", r is not None and "Mon 2am–Mon 4am" in r, f"got {r}")
check("labeled in mm/h, not a bogus 0%", r is not None and "(~1.2mm/h)" in r, f"got {r}")

r = _rain_windows({
    "time": [f"2026-07-06T{h:02d}:00" for h in range(6)],
    "precipitation_probability": [0, 0, 50, 80, 0, 0],
    "precipitation": [0.0] * 6,
})
check("probability labels unchanged", r is not None and "(~80%)" in r, f"got {r}")

r = _rain_windows({
    "time": [f"2026-07-06T{h:02d}:00" for h in range(6)],
    "precipitation_probability": [None] * 6,
    "precipitation": [0.0] * 6,
})
check("dry met.no horizon -> dry line", r is not None and "dry through your plan" in r)

# --------------------------------------------------------------------------- #
print("\nmet.no formatter — units, day bucketing, output shape:")

check("°C -> °F", round(_c_to_f(20.0)) == 68 and round(_c_to_f(0.0)) == 32)
check("m/s -> mph", round(_ms_to_mph(4.5)) == 10)
check("symbol map strips day/night variant",
      _met_symbol("clearsky_day") == "clear"
      and _met_symbol("heavyrainshowers_night") == "heavy rain showers")
check("unknown symbol falls back to base", _met_symbol("volcanicash_day") == "volcanicash")
check("missing symbol -> unknown", _met_symbol(None) == "unknown")


def _met_entry(iso_utc, temp_c, wind_ms=3.0, precip_1h=None, symbol="clearsky_day"):
    data = {"instant": {"details": {"air_temperature": temp_c, "wind_speed": wind_ms}}}
    if precip_1h is not None:
        data["next_1_hours"] = {
            "summary": {"symbol_code": symbol},
            "details": {"precipitation_amount": precip_1h},
        }
    return {"time": iso_utc, "data": data}


# 12:00Z Jul 6 == 8:00 AM ET; 36 hourly entries span two ET dates.
series = []
base = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
for h in range(36):
    t = base + timedelta(hours=h)
    series.append(_met_entry(
        t.strftime("%Y-%m-%dT%H:%M:%SZ"),
        temp_c=20.0 + (5 if 4 <= h <= 8 else 0),  # peak 25°C midday ET
        precip_1h=1.0 if h in (6, 7) else 0.0,
        symbol="lightrain" if h in (6, 7) else "partlycloudy_day",
    ))
out = _format_met_no(series, "Brooklyn, New York", 3, ET)
lines = out.splitlines()
check("same header as happy path", lines[0] == "Weather for Brooklyn, New York:")
check("Now line: °F + converted wind, no feels-like",
      lines[1] == "Now: 68°F, partly cloudy, wind 7 mph.", f"got {lines[1]!r}")
check("Today bucketed on ET date, midday symbol, 68–77°F (20–25°C)",
      any(ln.startswith("Today: partly cloudy, 68–77°F") for ln in lines),
      f"got {lines[2]!r}")
check("daily precip reported as mm", "~2.0mm precip." in out, f"got {out}")
check("Tomorrow present (entries cross local midnight)",
      any(ln.startswith("Tomorrow:") for ln in lines))
check("rain window in ET with mm/h label", "Mon 2pm–Mon 4pm (~1mm/h)" in out, f"got {out}")

try:
    _format_met_no([], "X", 3, ET)
    check("empty timeseries raises (total-failure path)", False, "no exception")
except ValueError:
    check("empty timeseries raises (total-failure path)", True)

# --------------------------------------------------------------------------- #
print("\ncron slash-command retry — decision predicate:")

import hal_orchestrator.services.cron as cron_svc  # noqa: E402
import hal_orchestrator.state as state  # noqa: E402
from hal_orchestrator.services.cron import should_retry_blank  # noqa: E402

check("slash + blank -> retry", should_retry_blank("/morning-brief", ""))
check("slash + whitespace reply -> retry", should_retry_blank("/morning-brief", "   \n"))
check("slash + None reply -> retry", should_retry_blank("/morning-brief", None))
check("leading whitespace before slash still counts",
      should_retry_blank("  /morning-brief", ""))
check("slash + real reply -> no retry",
      not should_retry_blank("/morning-brief", "Here's your brief"))
check("free-form + blank -> no retry (silence may be deliberate)",
      not should_retry_blank("check on the trains", ""))
check("empty prompt -> no retry", not should_retry_blank("", ""))
check("None prompt -> no retry", not should_retry_blank(None, ""))

# --------------------------------------------------------------------------- #
print("\ncron slash-command retry — _run_job flow (fake /api/message):")

from types import SimpleNamespace  # noqa: E402


class _FakeResp:
    def __init__(self, reply):
        self._reply = reply

    def raise_for_status(self):
        pass

    def json(self):
        return {"reply": self._reply, "side_messages": []}


class _FakeHttp:
    def __init__(self, replies):
        self.replies = list(replies)
        self.posts = 0

    async def post(self, url, json=None, headers=None, timeout=None):
        self.posts += 1
        return _FakeResp(self.replies.pop(0))


def _job(prompt):
    return SimpleNamespace(
        id="j1", phone="+1555", sender_phone=None, prompt=prompt,
        is_group=False, chat_id=None,
    )


def _drain():
    out = []
    while not state.outbox.empty():
        out.append(state.outbox.get_nowait())
    return out


_settings = SimpleNamespace(hal_bridge_secret="secret")
_orig_delay = cron_svc._SLASH_RETRY_DELAY_SECONDS
cron_svc._SLASH_RETRY_DELAY_SECONDS = 0
try:
    _drain()
    http = _FakeHttp(["", "Your brief: sunny, 3 meetings"])
    asyncio.run(cron_svc._run_job(_settings, http, _job("/morning-brief")))
    sent = _drain()
    check("blank slash reply -> retried once", http.posts == 2, f"got {http.posts}")
    check("retry's reply delivered",
          len(sent) == 1 and sent[0]["text"] == "Your brief: sunny, 3 meetings",
          f"got {sent}")

    http = _FakeHttp(["", ""])
    asyncio.run(cron_svc._run_job(_settings, http, _job("/morning-brief")))
    sent = _drain()
    check("double blank -> exactly one retry, no third call", http.posts == 2,
          f"got {http.posts}")
    check("double blank -> nothing sent (no apology text)", sent == [], f"got {sent}")

    http = _FakeHttp(["", "late answer"])
    asyncio.run(cron_svc._run_job(_settings, http, _job("check on the trains")))
    sent = _drain()
    check("free-form blank -> no retry", http.posts == 1, f"got {http.posts}")
    check("free-form blank -> nothing sent", sent == [], f"got {sent}")

    http = _FakeHttp(["all set for today"])
    asyncio.run(cron_svc._run_job(_settings, http, _job("/morning-brief")))
    sent = _drain()
    check("healthy slash reply -> single call, delivered",
          http.posts == 1 and len(sent) == 1 and sent[0]["to"] == "+1555", f"got {sent}")
finally:
    cron_svc._SLASH_RETRY_DELAY_SECONDS = _orig_delay

if failures:
    print(f"\n{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("\nall tests passed")
