"""Tests for the places tool: rendering, open_now pass-through, and the
missing-key / zero-result branches. Pure logic + a fake httpx layer; no network.

Run: python3 services/hal-orchestrator/tests_places.py
"""

import asyncio
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ag_common.config import HalOrchestratorConfig
from hal_orchestrator.tools.places import format_places, tool_places

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


# --------------------------------------------------------------------------- #
# Rendering (pure)
# --------------------------------------------------------------------------- #
print("place rendering:")

_PLACES = [
    {
        "displayName": {"text": "Brooklyn Roasting Company"},
        "formattedAddress": "25 Jay St, Brooklyn, NY 11201",
        "rating": 4.5,
        "userRatingCount": 1234,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "currentOpeningHours": {"openNow": True},
        "nationalPhoneNumber": "(718) 555-1234",
        "googleMapsUri": "https://maps.google.com/?cid=111",
        "websiteUri": "https://brooklynroasting.com",
    },
    {
        "displayName": {"text": "Corner Cafe"},
        "formattedAddress": "1 Fulton St, Brooklyn, NY",
        "rating": 4.1,
        "userRatingCount": 88,
        "priceLevel": "PRICE_LEVEL_INEXPENSIVE",
        "currentOpeningHours": {"openNow": False},
        "googleMapsUri": "https://maps.google.com/?cid=222",
    },
]

out = format_places(_PLACES, "coffee near Fort Greene")
check("numbered list", out.startswith("1. Brooklyn Roasting Company") and "2. Corner Cafe" in out, out)
check("rating + count with commas", "4.5★ (1,234)" in out, out)
check("price as $ signs", "$$" in out and "$" in out, out)
check("open-now status", "open now" in out, out)
check("closed status", "closed" in out, out)
check("address rendered", "25 Jay St, Brooklyn, NY 11201" in out, out)
check("phone rendered", "(718) 555-1234" in out, out)
check("maps uri included", "https://maps.google.com/?cid=111" in out, out)

# Robust to missing optional fields (no rating/price/phone/hours).
sparse = format_places([{"displayName": {"text": "Bare Spot"}, "formattedAddress": "X"}], "q")
check("sparse place renders", sparse.startswith("1. Bare Spot") and "X" in sparse, sparse)

check("zero results honest message", format_places([], "ramen near me") == "No places found for 'ramen near me'.")


# --------------------------------------------------------------------------- #
# tool_places with a fake httpx layer
# --------------------------------------------------------------------------- #
print("tool_places (fake http):")


class FakeResp:
    def __init__(self, status_code, payload, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class FakeHTTP:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self._resp


class FakeCtx:
    def __init__(self, key, resp, user_text="", current_location=None):
        self.settings = HalOrchestratorConfig(google_maps_api_key=key)
        self.http_client = FakeHTTP(resp)
        self.user_text = user_text
        self.current_location = current_location


async def run_tool():
    # Happy path renders and sends the query + field mask header.
    ctx = FakeCtx("k", FakeResp(200, {"places": _PLACES}))
    out = await tool_places({"query": "coffee near Fort Greene"}, ctx)
    check("happy path renders results", "Brooklyn Roasting Company" in out and "4.5★ (1,234)" in out, out)
    call = ctx.http_client.calls[0]
    check("textQuery sent", call["json"].get("textQuery") == "coffee near Fort Greene", call["json"])
    check("default maxResultCount 5", call["json"].get("maxResultCount") == 5, call["json"])
    check("api key header set", call["headers"].get("X-Goog-Api-Key") == "k", call["headers"])
    check("field mask header set", "places.displayName" in call["headers"].get("X-Goog-FieldMask", ""), call["headers"])
    check("open_now NOT sent by default", "openNow" not in call["json"], call["json"])

    # open_now filter passed through, and max_results capped at 8.
    ctx = FakeCtx("k", FakeResp(200, {"places": _PLACES}))
    await tool_places({"query": "ramen", "open_now": True, "max_results": 20}, ctx)
    call = ctx.http_client.calls[0]
    check("open_now → openNow true", call["json"].get("openNow") is True, call["json"])
    check("max_results capped at 8", call["json"].get("maxResultCount") == 8, call["json"])

    # Missing key → clear message, no HTTP call.
    ctx = FakeCtx("", FakeResp(200, {"places": _PLACES}))
    out = await tool_places({"query": "coffee"}, ctx)
    check("missing key → clear error", "not configured" in out, out)
    check("missing key → no http call", ctx.http_client.calls == [], ctx.http_client.calls)

    # Missing query → error.
    ctx = FakeCtx("k", FakeResp(200, {"places": []}))
    out = await tool_places({}, ctx)
    check("missing query → error", "query is required" in out, out)

    # Zero results → honest message.
    ctx = FakeCtx("k", FakeResp(200, {"places": []}))
    out = await tool_places({"query": "unobtanium bistro"}, ctx)
    check("zero results honest", out == "No places found for 'unobtanium bistro'.", out)

    # 403 permission denied → mentions API not enabled.
    ctx = FakeCtx("k", FakeResp(403, {"error": {"status": "PERMISSION_DENIED", "message": "denied"}}))
    out = await tool_places({"query": "coffee"}, ctx)
    check("403 → mentions Places API enablement", "may not be enabled" in out, out)

    # Other HTTP error → status + message.
    ctx = FakeCtx("k", FakeResp(400, {"error": {"message": "bad request"}}))
    out = await tool_places({"query": "coffee"}, ctx)
    check("HTTP error → status + message", "HTTP 400" in out and "bad request" in out, out)

    # Live-location turn without a location → no-guess boundary, no HTTP call.
    ctx = FakeCtx("k", FakeResp(200, {"places": _PLACES}), user_text="coffee near me")
    out = await tool_places({"query": "coffee"}, ctx)
    check("live location missing → no-guess message", "live location is unavailable" in out, out)
    check("live location missing → no http call", ctx.http_client.calls == [], ctx.http_client.calls)

    # Live-location turn with a label → query rebuilt around the live label,
    # overriding any model-guessed area.
    ctx = FakeCtx(
        "k",
        FakeResp(200, {"places": _PLACES}),
        user_text="coffee near me",
        current_location={"label": "Fort Greene"},
    )
    await tool_places({"query": "coffee near Park Slope"}, ctx)
    call = ctx.http_client.calls[0]
    check(
        "live label overrides guessed area",
        call["json"].get("textQuery") == "coffee near Fort Greene",
        call["json"],
    )


asyncio.run(run_tool())

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all tests passed")
