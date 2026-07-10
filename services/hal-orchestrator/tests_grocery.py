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
    AsinCandidate,
    GroceryError,
    _extract_share_url,
    _mcp_payload,
    _parse_mcp_body,
    _structure_line,
    amazon_cart_url,
    amazon_search_links,
    best_asin_candidate,
    cart_quantity,
    coerce_items,
    coerce_line_items,
    coerce_products,
    extract_asins,
    is_perishable,
    parse_ingredient_lines,
    parse_line_items,
    recipe_arguments,
    score_candidate,
    shopping_list_arguments,
    strip_multiplier,
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
print("structured line items — quantity/unit/name/displayText:")


def _one(line):
    return _structure_line(line)


yog = _one("170 g Greek yogurt")
check("qty parsed", yog["quantity"] == 170, yog)
check("unit parsed", yog["unit"] == "g", yog)
check("name is the remainder", yog["name"] == "Greek yogurt", yog)
check("displayText is verbatim", yog["displayText"] == "170 g Greek yogurt", yog)

half = _one("½ scoop protein powder")
check("unicode ½ -> 0.5", half["quantity"] == 0.5, half)
check("scoop is a unit", half["unit"] == "scoop", half)
check("½ name", half["name"] == "protein powder", half)

check("mixed unicode 1½ cup -> 1.5", _one("1½ cup oats")["quantity"] == 1.5)
check("ascii fraction 3/4 -> 0.75", _one("3/4 cup rice")["quantity"] == 0.75)
check("mixed ascii 1 1/2 -> 1.5", _one("1 1/2 tbsp honey")["quantity"] == 1.5)
check("decimal preserved", _one("0.5 l milk")["quantity"] == 0.5)
check("integer stays int (not 170.0)", isinstance(yog["quantity"], int), type(yog["quantity"]))

unitless = _one("1 big handful spinach")
check("unrecognized unit -> each", unitless["unit"] == "each", unitless)
check("unitless keeps quantity", unitless["quantity"] == 1, unitless)
check("unitless name keeps the descriptor", unitless["name"] == "big handful spinach", unitless)

bare = _one("Cinnamon")
check("no quantity -> 1", bare["quantity"] == 1, bare)
check("no unit -> each", bare["unit"] == "each", bare)
check("bare name", bare["name"] == "Cinnamon", bare)

smoothie_items = parse_line_items(SMOOTHIE)
check("every line item has name+quantity+unit", all(i["name"] and i["quantity"] and i["unit"] for i in smoothie_items), smoothie_items)
check(
    "protein powder line item structured (whey, scoop)",
    any(i["unit"] == "scoop" and i["name"] == "protein powder (whey)" for i in smoothie_items),
    smoothie_items,
)
check(
    "coerce_line_items normalizes a caller dict + drops extra keys",
    coerce_line_items([{"name": "oats", "quantity": 2, "unit": "cup", "bogus": 1}])
    == [{"name": "oats", "quantity": 2, "unit": "cup", "displayText": "oats"}],
    coerce_line_items([{"name": "oats", "quantity": 2, "unit": "cup", "bogus": 1}]),
)

# --------------------------------------------------------------------------- #
print("MCP payload construction + validation against the REAL Instacart schemas:")

# Captured verbatim from an unauthenticated tools/list on
# https://mcp.instacart.com/mcp (2026-07-09). Line items require `name`; a line
# item missing quantity OR unit is silently dropped, so we always send both.
_LINE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "quantity": {"type": "number"},
        "unit": {"type": "string"},
        "displayText": {"type": "string"},
    },
    "required": ["name"],
    "additionalProperties": False,
}
SHOPPING_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "image_url": {"type": "string"},
        "expires_in": {"type": "number"},
        "instructions": {"type": "array", "items": {"type": "string"}},
        "lineItems": {"type": "array", "items": _LINE_ITEM_SCHEMA, "minItems": 1},
        "landingPageConfiguration": {"type": "object", "additionalProperties": True},
    },
    "required": ["title", "lineItems"],
    "additionalProperties": False,
}
RECIPE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "image_url": {"type": "string"},
        "author": {"type": "string"},
        "servings": {"type": "number"},
        "cooking_time": {"type": "number"},
        "instructions": {"type": "array", "items": {"type": "string"}},
        "ingredients": {"type": "array", "items": _LINE_ITEM_SCHEMA, "minItems": 1},
    },
    "required": ["title", "ingredients"],
    "additionalProperties": False,
}

_TYPES = {"object": dict, "array": list, "string": str, "number": (int, float), "boolean": bool}


def schema_errors(instance, schema, path="$"):
    """Minimal JSON-Schema check: types, required, additionalProperties, minItems."""
    errors = []
    expected = schema.get("type")
    if expected and not isinstance(instance, _TYPES[expected]):
        # bool is an int subclass; keep numbers from matching booleans.
        if not (expected == "number" and isinstance(instance, bool)):
            errors.append(f"{path}: expected {expected}, got {type(instance).__name__}")
            return errors
    if expected == "object":
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required '{key}'")
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append(f"{path}: additionalProperties violation '{key}'")
        for key, val in instance.items():
            if key in props:
                errors += schema_errors(val, props[key], f"{path}.{key}")
    elif expected == "array":
        if len(instance) < schema.get("minItems", 0):
            errors.append(f"{path}: fewer than minItems {schema['minItems']}")
        item_schema = schema.get("items")
        if item_schema:
            for i, el in enumerate(instance):
                errors += schema_errors(el, item_schema, f"{path}[{i}]")
    return errors


payload = _mcp_payload("create-shopping-list", shopping_list_arguments("Smoothie run", SMOOTHIE))
check("jsonrpc 2.0", payload["jsonrpc"] == "2.0", payload)
check("method tools/call", payload["method"] == "tools/call", payload)
check("params.name is the MCP tool", payload["params"]["name"] == "create-shopping-list", payload)
check("has an id", "id" in payload, payload)

sl_args = payload["params"]["arguments"]
check("shopping list uses lineItems (not items)", "lineItems" in sl_args and "items" not in sl_args, list(sl_args))
sl_errors = schema_errors(sl_args, SHOPPING_LIST_SCHEMA)
check("shopping-list payload validates against the real schema", sl_errors == [], sl_errors)
check(
    "every shopping-list line item has name+quantity+unit populated",
    all(li.get("name") and "quantity" in li and li.get("unit") for li in sl_args["lineItems"]),
    sl_args["lineItems"],
)

rp_args = recipe_arguments(
    "Green smoothie", SMOOTHIE, instructions="Blend everything\nServe cold"
)
rp_errors = schema_errors(rp_args, RECIPE_SCHEMA)
check("recipe payload validates against the real schema", rp_errors == [], rp_errors)
check("recipe instructions are an array of strings", rp_args["instructions"] == ["Blend everything", "Serve cold"], rp_args["instructions"])
check(
    "every recipe ingredient has name+quantity+unit populated",
    all(i.get("name") and "quantity" in i and i.get("unit") for i in rp_args["ingredients"]),
    rp_args["ingredients"],
)

# Negative control: the validator actually catches a bad shape.
bad = {"title": "x", "lineItems": [{"name": "oats", "surprise": 1}]}
check("validator flags additionalProperties + missing keys", schema_errors(bad, SHOPPING_LIST_SCHEMA) != [], "validator too lax")

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

from hal_orchestrator.tools.plugins.grocery import tool_shopping  # noqa: E402


def _ctx(key=""):
    return SimpleNamespace(
        settings=SimpleNamespace(instacart_api_key=key),
        http_client=None,
        is_group=False,
    )


no_key = asyncio.run(tool_shopping({"action": "list", "items": "oats, chia"}, _ctx("")))
check(
    "empty key -> automatic Whole Foods fallback links",
    "amazon.com/s?k=oats&i=wholefoods" in no_key and "amazon.com/s?k=chia&i=wholefoods" in no_key,
    no_key,
)
check("empty-key message never leaks 'error'/'exception'", "error" not in no_key.lower() and "exception" not in no_key.lower(), no_key)

no_key_recipe = asyncio.run(
    tool_shopping({"action": "recipe", "title": "Smoothie", "ingredients": "oats, chia"}, _ctx(""))
)
check(
    "empty key -> recipe also falls back to WF links",
    "amazon.com/s?k=oats&i=wholefoods" in no_key_recipe,
    no_key_recipe,
)

wf_reply = asyncio.run(
    tool_shopping({"action": "wholefoods_links", "items": "oats, chia"}, _ctx(""))
)
check("wholefoods_links works with no Instacart key", "amazon.com/s?k=oats&i=wholefoods" in wf_reply, wf_reply)

# --------------------------------------------------------------------------- #
print("Amazon ASIN extraction — /dp/ and /gp/product/, reject near-misses:")

check(
    "/dp/ ASIN extracted",
    extract_asins("https://www.amazon.com/Organic-Chia-Seeds/dp/B00KFEXGO4/ref=sr_1_3")
    == ["B00KFEXGO4"],
    extract_asins("https://www.amazon.com/Organic-Chia-Seeds/dp/B00KFEXGO4/ref=sr_1_3"),
)
check(
    "/gp/product/ ASIN extracted",
    extract_asins("https://www.amazon.com/gp/product/B0016AXNS2") == ["B0016AXNS2"],
)
check(
    "ASIN before a query string extracted",
    extract_asins("https://www.amazon.com/dp/B0016AXNS2?th=1") == ["B0016AXNS2"],
)
check(
    "9-char near-miss rejected",
    extract_asins("https://www.amazon.com/dp/B00KFEXG0/ref=x") == [],
    extract_asins("https://www.amazon.com/dp/B00KFEXG0/ref=x"),
)
check(
    "lowercase near-miss rejected",
    extract_asins("https://www.amazon.com/dp/b00kfexgo4") == [],
)
check(
    "11-char alnum run is not treated as an ASIN",
    extract_asins("https://www.amazon.com/dp/B00KFEXGO4X") == [],
    extract_asins("https://www.amazon.com/dp/B00KFEXGO4X"),
)
check(
    "search URL (no /dp/) yields nothing",
    extract_asins("https://www.amazon.com/s?k=chia+seeds") == [],
)

# --------------------------------------------------------------------------- #
print("Amazon candidate scoring — the matching title wins:")

_dp = "https://www.amazon.com/dp/B00KFEXGO4"
s_match = score_candidate("chia seeds", "Organic Chia Seeds, 2 lb Bag", _dp)
s_wrong = score_candidate("chia seeds", "Roasted Sunflower Seeds Snack", _dp)
check("matching title scores higher than a wrong one", s_match > s_wrong, (s_match, s_wrong))
check("full-overlap match clears 1.0 (with /dp/ bonus)", s_match > 1.0, s_match)
check(
    "obvious mismatch (head noun absent) scores at or below zero",
    score_candidate("rolled oats", "Stainless Steel Water Bottle", _dp) <= 0,
    score_candidate("rolled oats", "Stainless Steel Water Bottle", _dp),
)
check(
    "a Prime Video / streaming hit is rejected (not a cart item)",
    score_candidate("Project Hail Mary", "Watch Project Hail Mary | Prime Video", _dp) <= 0,
    score_candidate("Project Hail Mary", "Watch Project Hail Mary | Prime Video", _dp),
)
check(
    "a real 'Apple Watch' product is NOT caught by the streaming filter",
    score_candidate("apple watch", "Apple Watch Series 9 GPS 45mm", _dp) > 0,
    score_candidate("apple watch", "Apple Watch Series 9 GPS 45mm", _dp),
)

_results = [
    {"title": "Roasted Sunflower Seeds Snack", "url": "https://www.amazon.com/dp/B0011111AA"},
    {"title": "Organic Chia Seeds, 2 lb Bag", "url": "https://www.amazon.com/Chia/dp/B00KFEXGO4/ref=x"},
]
_best = best_asin_candidate("chia seeds", _results)
check("best_asin_candidate returns the chia match", _best is not None and _best.asin == "B00KFEXGO4", _best)
check("best candidate carries its score", _best is not None and _best.score > 1.0, _best)
check("no results -> None", best_asin_candidate("chia seeds", []) is None)
check(
    "results without any ASIN -> None",
    best_asin_candidate("chia", [{"title": "Chia", "url": "https://x.com/s?k=chia"}]) is None,
)

# --------------------------------------------------------------------------- #
print("Amazon cart URL builder — indexed params, encoding, associate tag:")

cart_url = amazon_cart_url([("B00KFEXGO4", 1), ("B0016AXNS2", 2)])
check("cart add.html endpoint", cart_url.startswith("https://www.amazon.com/gp/aws/cart/add.html?"), cart_url)
check("item 1 ASIN + quantity", "ASIN.1=B00KFEXGO4" in cart_url and "Quantity.1=1" in cart_url, cart_url)
check("item 2 ASIN + quantity", "ASIN.2=B0016AXNS2" in cart_url and "Quantity.2=2" in cart_url, cart_url)
check("no AssociateTag param when omitted", "AssociateTag" not in cart_url, cart_url)
_tagged = amazon_cart_url([("B00KFEXGO4", 1)], associate_tag="hal-20")
check("AssociateTag included when configured", "AssociateTag=hal-20" in _tagged, _tagged)
check(
    "associate tag is URL-encoded",
    "AssociateTag=my+tag" in amazon_cart_url([("B00KFEXGO4", 1)], associate_tag="my tag"),
    amazon_cart_url([("B00KFEXGO4", 1)], associate_tag="my tag"),
)
check("quantity coerces to int (no 1.0)", "Quantity.1=1" in amazon_cart_url([("B00KFEXGO4", 1.0)]))

check("cart_quantity default 1 for a gram amount", cart_quantity("170 g Greek yogurt") == 1)
check("cart_quantity 1 for a plain item", cart_quantity("chia seeds") == 1)
check("cart_quantity reads a '2 x' multiplier", cart_quantity("2 x sparkling water") == 2)
check("cart_quantity reads '3× cans'", cart_quantity("3× cans black beans") == 3)
check("cart_quantity ignores a count that isn't 'N x'", cart_quantity("2 cans black beans") == 1)

# --------------------------------------------------------------------------- #
print("Amazon perishable routing — fresh -> Whole Foods, pantry -> discovery:")

check("spinach is perishable", is_perishable("a handful of spinach"))
check("greek yogurt is perishable", is_perishable("170 g Greek yogurt"))
check("frozen blueberries is perishable", is_perishable("100 g frozen blueberries"))
check("chia is not perishable -> discovery", is_perishable("1 tbsp chia") is False)
check("oats are not perishable -> discovery", is_perishable("40 g oats") is False)
check("protein powder is not perishable -> discovery", is_perishable("1 scoop protein powder (whey)") is False)
check("psyllium is not perishable", is_perishable("1 tsp psyllium (not a heap)") is False)
check("peanut butter stays on Amazon (pantry override)", is_perishable("1 tbsp peanut butter") is False)
check("soy milk is pantry-stable (override) -> discovery", is_perishable("250 ml soy milk") is False)

# --------------------------------------------------------------------------- #
print("General-product coercion — no ingredient parsing, quantity prefix, search links:")

check(
    "a book title with 'or' is NOT truncated as an alternation",
    coerce_products("Do Androids Dream of Electric Sheep") == ["Do Androids Dream of Electric Sheep"],
    coerce_products("Do Androids Dream of Electric Sheep"),
)
check(
    "'whey, casein, or soy' is truncated by the GROCERY parser (contrast)",
    coerce_items("whey, casein, or soy protein powder") == ["whey protein powder"],
    coerce_items("whey, casein, or soy protein powder"),
)
check(
    "a list passes through intact (commas inside a title preserved)",
    coerce_products(["Eats, Shoots & Leaves", "desk lamp"]) == ["Eats, Shoots & Leaves", "desk lamp"],
    coerce_products(["Eats, Shoots & Leaves", "desk lamp"]),
)
check(
    "a comma/newline string splits into products (no non-item filtering)",
    coerce_products("Project Hail Mary, desk lamp\n2x AA batteries")
    == ["Project Hail Mary", "desk lamp", "2x AA batteries"],
    coerce_products("Project Hail Mary, desk lamp\n2x AA batteries"),
)
check("coerce_products dedupes case-insensitively", coerce_products("lamp, Lamp, LAMP") == ["lamp"])

check("strip_multiplier drops a leading '2x'", strip_multiplier("2x AA batteries") == "AA batteries")
check("strip_multiplier drops a leading '3× '", strip_multiplier("3× notebooks") == "notebooks")
check("strip_multiplier leaves a plain name alone", strip_multiplier("desk lamp") == "desk lamp")
check(
    "strip_multiplier does NOT eat a grocery amount ('170 g')",
    strip_multiplier("170 g oats") == "170 g oats",
)

_asl = amazon_search_links(["Project Hail Mary", "desk lamp"])
check("amazon_search_links: general storefront (no wholefoods scope)", "i=wholefoods" not in _asl, _asl)
check("amazon_search_links: url-encoded query", "k=Project+Hail+Mary" in _asl and "k=desk+lamp" in _asl, _asl)
check("amazon_search_links: numbered per item", _asl.startswith("1. Project Hail Mary: "), _asl)

# --------------------------------------------------------------------------- #
print("Amazon split reply — cart link + Whole Foods bucket + honest miss line:")


def _fake_discover(found_map):
    async def _f(ctx, items, **kwargs):
        return {it: found_map.get(it) for it in items}

    return _f


_CHIA = AsinCandidate("B00KFEXGO4", "Organic Chia Seeds", "https://www.amazon.com/dp/B00KFEXGO4", 1.1)
_OATS = AsinCandidate("B000P6G0MS", "Rolled Oats 2lb", "https://www.amazon.com/dp/B000P6G0MS", 1.1)

_orig_discover = grocery.discover_asins
grocery.discover_asins = _fake_discover({"1 tbsp chia": _CHIA, "40 g oats": _OATS})
try:
    split = asyncio.run(
        tool_shopping(
            {
                "action": "list",
                "items": "1 tbsp chia\n40 g oats\na handful of spinach\n170 g Greek yogurt\n1 tsp psyllium",
            },
            _ctx(""),
        )
    )
finally:
    grocery.discover_asins = _orig_discover

check(
    "cart block present with both discovered ASINs",
    "gp/aws/cart/add.html" in split and "ASIN.1=B00KFEXGO4" in split and "ASIN.2=B000P6G0MS" in split,
    split,
)
check("cart block counts 2 items", "Amazon cart (2 items)" in split, split)
check(
    "fresh bucket -> Whole Foods links for spinach + yogurt",
    "i=wholefoods" in split and "spinach" in split and "yogurt" in split.lower(),
    split,
)
check("honest miss line names psyllium", "psyllium" in split and "Couldn't pin" in split, split)
check("split reply leaks no error words", "error" not in split.lower() and "exception" not in split.lower(), split)

# --------------------------------------------------------------------------- #
print("amazon_cart action — general products, quantity prefix, no perishable routing:")

_BOOK = AsinCandidate("B08GB58KD5", "Project Hail Mary: A Novel", "https://www.amazon.com/dp/B08GB58KD5", 1.2)
_BATT = AsinCandidate("B00MNV8E0C", "Energizer AA Batteries 24 Pack", "https://www.amazon.com/dp/B00MNV8E0C", 1.0)

# Discovery is keyed by the STRIPPED search name ("2x AA batteries" -> "AA batteries").
grocery.discover_asins = _fake_discover({"Project Hail Mary": _BOOK, "AA batteries": _BATT})
try:
    cart_reply = asyncio.run(
        tool_shopping(
            {"action": "amazon_cart", "items": ["Project Hail Mary", "2x AA batteries", "whole milk"]},
            _ctx(""),
        )
    )
finally:
    grocery.discover_asins = _orig_discover

check("amazon_cart puts the book in the cart link", "ASIN.1=B08GB58KD5" in cart_reply, cart_reply)
check(
    "'2x' prefix becomes Quantity 2 for the batteries",
    "ASIN.2=B00MNV8E0C" in cart_reply and "Quantity.2=2" in cart_reply,
    cart_reply,
)
check(
    "no perishable routing: 'whole milk' is searched, missed -> GENERAL Amazon link",
    "k=whole+milk" in cart_reply and "i=wholefoods" not in cart_reply,
    cart_reply,
)
check("amazon_cart leaks no error words", "error" not in cart_reply.lower() and "exception" not in cart_reply.lower(), cart_reply)

# --------------------------------------------------------------------------- #
print("Amazon fallback — nothing found at all -> current all-Whole-Foods reply:")

grocery.discover_asins = _fake_discover({})
try:
    all_wf = asyncio.run(tool_shopping({"action": "list", "items": "widget, gadget"}, _ctx("")))
finally:
    grocery.discover_asins = _orig_discover

check(
    "all-miss list falls back to WF links for every item",
    "i=wholefoods" in all_wf and "k=widget" in all_wf and "k=gadget" in all_wf,
    all_wf,
)
check("fallback carries no Amazon cart link", "gp/aws/cart/add.html" not in all_wf, all_wf)

# --------------------------------------------------------------------------- #
print("web_search DDG redirect unwrapping (ASIN discovery depends on it):")

from hal_orchestrator.tools.web_search import _unwrap_ddg_url  # noqa: E402

check(
    "uddg redirect unwrapped to the real Amazon URL",
    _unwrap_ddg_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.amazon.com%2Fdp%2FB00KFEXGO4&rut=x")
    == "https://www.amazon.com/dp/B00KFEXGO4",
    _unwrap_ddg_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.amazon.com%2Fdp%2FB00KFEXGO4&rut=x"),
)
check(
    "a plain (non-redirect) URL passes through unchanged",
    _unwrap_ddg_url("https://www.amazon.com/dp/B00KFEXGO4") == "https://www.amazon.com/dp/B00KFEXGO4",
)

# --------------------------------------------------------------------------- #
print("plugin registration — the drop-in reaches the model:")

from hal_orchestrator.tools.specs import get_tool_spec, model_tools  # noqa: E402

declared_names = {
    d["name"] for group in model_tools() for d in group["function_declarations"]
}
check("shopping in model_tools() declarations", "shopping" in declared_names, sorted(declared_names))
check("old name grocery is gone", "grocery" not in declared_names, sorted(declared_names))

spec = get_tool_spec("shopping")
check("spec registered", spec is not None)
check("scopes allow dm AND group", spec.scopes == frozenset({"dm", "group"}), spec.scopes)
check("risk=write", spec.risk == "write", spec.risk)
check("timeout 60s (covers the ASIN search batch)", spec.timeout_seconds == 60, spec.timeout_seconds)
check("not parallel_safe (it writes)", spec.parallel_safe is False)
check(
    "handler points at the plugin",
    spec.handler == "hal_orchestrator.tools.plugins.grocery:tool_shopping",
    spec.handler,
)
check("declaration name matches spec name (shopping)", spec.declaration["name"] == "shopping")

# --------------------------------------------------------------------------- #
if failures:
    print(f"\n{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("\nall passed")
