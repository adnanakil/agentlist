"""Tests for the grocery tool: recipe/list parsing, Whole Foods fallback links,
the Instacart MCP client's payload + response parsing, the empty-key graceful
path, and that the drop-in plugin actually reaches the model.

The parsing is exercised against the real message from the incident that
prompted this tool — a user texted HAL a protein-smoothie recipe and asked it to
"put all this stuff in my Whole Foods shopping cart." Live HTTP against Instacart
is not exercised here; the MCP body parser is fed captured JSON + SSE shapes.

Run: uv run python tests_grocery.py
"""

import asyncio
import os
import sys
from types import SimpleNamespace

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services import grocery  # noqa: E402
from hal_orchestrator.services.grocery import (  # noqa: E402
    GroceryError,
    _extract_share_url,
    _mcp_payload,
    _parse_mcp_body,
    coerce_items,
    parse_ingredient_lines,
    wholefoods_search_links,
)

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


# --------------------------------------------------------------------------- #
print("parse_ingredient_lines — the real smoothie message from the incident:")

SMOOTHIE = """Morning smoothie:
- 250 ml soy milk
- 170 g Greek yogurt
- 1 scoop protein powder (whey, casein, pea, or soy)
- 40 g oats
- 1 tbsp chia
- 1 tsp psyllium (not a heap)
- 100 g frozen blueberries
- a handful of spinach
- 1 tbsp peanut butter
- Cinnamon, ice, and water as needed for thickness
"""

parsed = parse_ingredient_lines(SMOOTHIE)
check("header line dropped", "Morning smoothie:" not in parsed and "Morning smoothie" not in parsed)
check("soy milk kept with quantity", "250 ml soy milk" in parsed, parsed)
check("greek yogurt kept with quantity", "170 g Greek yogurt" in parsed, parsed)
check(
    "protein powder alternation -> first option only",
    "1 scoop protein powder (whey)" in parsed,
    parsed,
)
check("psyllium 'not a heap' preserved", "1 tsp psyllium (not a heap)" in parsed, parsed)
check("frozen blueberries kept", "100 g frozen blueberries" in parsed, parsed)
check("spinach kept", "a handful of spinach" in parsed, parsed)
check("peanut butter kept", "1 tbsp peanut butter" in parsed, parsed)
check("cinnamon salvaged from the mixed line", "Cinnamon" in parsed, parsed)
check("ice dropped as a non-item", "ice" not in [p.lower() for p in parsed], parsed)
check(
    "water-as-needed dropped as a non-item",
    not any("water" in p.lower() for p in parsed),
    parsed,
)
check("exactly the 10 real items", len(parsed) == 10, f"{len(parsed)}: {parsed}")

print("parse_ingredient_lines — bare alternation, comma blob, dedupe:")
check(
    "bare 'A, B, or C noun' -> first option",
    parse_ingredient_lines("whey, casein, pea, or soy protein powder") == ["whey protein powder"],
    parse_ingredient_lines("whey, casein, pea, or soy protein powder"),
)
check(
    "single-line comma blob splits into items",
    parse_ingredient_lines("soy milk, greek yogurt, oats") == ["soy milk", "greek yogurt", "oats"],
    parse_ingredient_lines("soy milk, greek yogurt, oats"),
)
check(
    "quantity-only comma fragment dropped",
    parse_ingredient_lines("Greek yogurt, 170 g") == ["Greek yogurt"],
    parse_ingredient_lines("Greek yogurt, 170 g"),
)
check("duplicates collapsed", parse_ingredient_lines("oats\noats\nOATS") == ["oats"])
check("coerce_items passes a list through cleanly", coerce_items(["  oats ", "", "chia"]) == ["oats", "chia"])
check("coerce_items parses a string", coerce_items("oats, chia") == ["oats", "chia"])

# --------------------------------------------------------------------------- #
print("wholefoods_search_links — URL encoding + numbered list:")

wf = wholefoods_search_links(["Greek yogurt", "chia seeds"])
check("numbered", wf.startswith("1. Greek yogurt: "), wf)
check("second item numbered 2", "\n2. chia seeds: " in wf, wf)
check("amazon wholefoods storefront + urlencoded query", "https://www.amazon.com/s?k=Greek+yogurt&i=wholefoods" in wf, wf)
check("spaces encoded as + in every link", "k=chia+seeds&i=wholefoods" in wf, wf)
check("one line per item", len(wf.splitlines()) == 2, wf)

# --------------------------------------------------------------------------- #
print("MCP payload construction:")

payload = _mcp_payload("create-shopping-list", {"title": "T", "items": ["a", "b"]})
check("jsonrpc 2.0", payload["jsonrpc"] == "2.0", payload)
check("method tools/call", payload["method"] == "tools/call", payload)
check("params.name is the MCP tool", payload["params"]["name"] == "create-shopping-list", payload)
check("params.arguments carried through", payload["params"]["arguments"] == {"title": "T", "items": ["a", "b"]}, payload)
check("has an id", "id" in payload, payload)

# --------------------------------------------------------------------------- #
print("MCP response -> share URL (JSON, event-stream, and missing):")

URL = "https://www.instacart.com/store/shopping_lists/12345"

json_body = (
    '{"jsonrpc":"2.0","id":1,"result":{"content":['
    '{"type":"text","text":"Your shopping list is ready: ' + URL + '"}]}}'
)
check(
    "JSON body: URL pulled from text content",
    _extract_share_url(_parse_mcp_body(json_body, "application/json")) == URL,
)

json_keyed = '{"jsonrpc":"2.0","id":1,"result":{"products_link_url":"%s","other":"noise"}}' % URL
check(
    "JSON body: preferred link key wins",
    _extract_share_url(_parse_mcp_body(json_keyed, "application/json")) == URL,
)

sse_body = (
    "event: message\n"
    'data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text",'
    '"text":"Here you go: ' + URL + '"}]}}\n\n'
)
check(
    "event-stream body: URL parsed from data: line",
    _extract_share_url(_parse_mcp_body(sse_body, "text/event-stream")) == URL,
)

missing = '{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"done, no link"}]}}'
try:
    _extract_share_url(_parse_mcp_body(missing, "application/json"))
    check("missing-URL response raises", False, "no error raised")
except GroceryError:
    check("missing-URL response raises GroceryError", True)

err_body = '{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"bad key"}}'
try:
    _extract_share_url(_parse_mcp_body(err_body, "application/json"))
    check("JSON-RPC error raises", False, "no error raised")
except GroceryError as exc:
    check("JSON-RPC error surfaces the message", "bad key" in str(exc), str(exc))

# --------------------------------------------------------------------------- #
print("tool handler — empty key is graceful, WF fallback needs no key:")

from hal_orchestrator.tools.plugins.grocery import tool_grocery  # noqa: E402


def _ctx(key=""):
    return SimpleNamespace(
        settings=SimpleNamespace(instacart_api_key=key),
        http_client=None,
        is_group=False,
    )


no_key = asyncio.run(tool_grocery({"action": "list", "items": "oats, chia"}, _ctx("")))
check("empty key -> graceful message, not a raw error", no_key == grocery.NO_KEY_MESSAGE, no_key)
check("empty-key message never leaks 'error'/'exception'", "error" not in no_key.lower() and "exception" not in no_key.lower(), no_key)

wf_reply = asyncio.run(
    tool_grocery({"action": "wholefoods_links", "items": "oats, chia"}, _ctx(""))
)
check("wholefoods_links works with no Instacart key", "amazon.com/s?k=oats&i=wholefoods" in wf_reply, wf_reply)

# --------------------------------------------------------------------------- #
print("plugin registration — the drop-in reaches the model:")

from hal_orchestrator.tools.specs import get_tool_spec, model_tools  # noqa: E402

declared_names = {
    d["name"] for group in model_tools() for d in group["function_declarations"]
}
check("grocery in model_tools() declarations", "grocery" in declared_names, sorted(declared_names))

spec = get_tool_spec("grocery")
check("spec registered", spec is not None)
check("scopes allow dm AND group", spec.scopes == frozenset({"dm", "group"}), spec.scopes)
check("risk=write", spec.risk == "write", spec.risk)
check("timeout ~30s", spec.timeout_seconds == 30, spec.timeout_seconds)
check("not parallel_safe (it writes)", spec.parallel_safe is False)
check(
    "handler points at the plugin",
    spec.handler == "hal_orchestrator.tools.plugins.grocery:tool_grocery",
    spec.handler,
)
check("declaration name matches spec name", spec.declaration["name"] == "grocery")

# --------------------------------------------------------------------------- #
if failures:
    print(f"\n{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("\nall passed")
