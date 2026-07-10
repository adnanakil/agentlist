"""grocery — turn a pasted recipe/list into ONE tap-to-shop link.

The honest platform reality: Amazon/Whole Foods has no cart API you can fill
directly (Whole Foods left Instacart in 2019; Amazon keeps its carts closed).
The best legitimate one-tap experience is Instacart's developer API — we build a
shopping list or recipe page server-side and text the user a single link. They
tap it, pick their own local store (Wegmans, Costco, Key Food…), and everything
is pre-filled for checkout. For a Whole Foods loyalist the graceful fallback is
per-item Whole Foods storefront search links on Amazon.

Instacart's link builder is an MCP server: JSON-RPC 2.0 ``tools/call`` over
POST https://mcp.instacart.com/mcp with a Bearer key. It can answer as JSON or
as a Server-Sent-Events (text/event-stream) body, and the shareable URL lives
somewhere inside the ``result`` — both are handled here. The pure helpers
(parse_ingredient_lines, wholefoods_search_links, payload/URL parsing) do no I/O
and are unit-tested in tests_grocery.py.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

import httpx
import structlog

log = structlog.get_logger()

MCP_URL = "https://mcp.instacart.com/mcp"

# Amazon storefront search scoped to the Whole Foods Market merchant.
_WF_SEARCH = "https://www.amazon.com/s?k={q}&i=wholefoods"

class GroceryError(Exception):
    """The Instacart link couldn't be built (transport, API, or missing URL)."""


# --------------------------------------------------------------------------- #
# Pure text helpers — no DB, no network.
# --------------------------------------------------------------------------- #

_BULLET = re.compile(r"^\s*(?:[-*•·▪◦‣]+|\d+[.)])\s*")
_WS = re.compile(r"\s+")

# Tap-water / freezer staples nobody adds to a cart, plus "as needed" filler.
_NON_ITEM_WORDS = {"ice", "water"}
_NON_ITEM_PHRASES = (
    "as needed",
    "to taste",
    "for thickness",
    "for serving",
    "for garnish",
    "if needed",
)
# A part that is purely a quantity (e.g. a "Greek yogurt, 170 g" comma fragment).
_QTY_ONLY = re.compile(
    r"^[\d\s./½¼¾⅓⅔⅛⅜⅝⅞+-]+ *"
    r"(g|kg|mg|ml|l|oz|lb|lbs|tbsp|tsp|cup|cups|scoop|scoops|handful|handfuls|"
    r"pinch|pinches|clove|cloves|can|cans|slice|slices|piece|pieces)?\.?$",
    re.I,
)


def _clean(s: str) -> str:
    return _WS.sub(" ", (s or "").strip()).strip(" ,.;")


def _first_alternative(s: str) -> str:
    """Collapse an "A, B, or C" alternation to just its first option.

    Handles a parenthetical form — "protein powder (whey, casein, pea, or soy)"
    -> "protein powder (whey)" — and a bare form — "whey, casein, pea, or soy
    protein powder" -> "whey protein powder".
    """

    def _paren(m: re.Match) -> str:
        first = re.split(r",|\bor\b", m.group(1), maxsplit=1, flags=re.I)[0].strip()
        return f"({first})" if first else ""

    reduced = re.sub(r"\(([^)]*\bor\b[^)]*)\)", _paren, s, flags=re.I)
    if reduced != s:
        return _WS.sub(" ", reduced).strip()

    m = re.match(r"^(.+?),\s*(?:.+,\s*)?or\s+(\S+)(\s+.+)?$", s, re.I)
    if not m:
        return s
    first, tail = m.group(1).strip(), (m.group(3) or "").strip()
    return f"{first} {tail}".strip() if tail else first


def _has_alternation(s: str) -> bool:
    return bool(
        re.search(r"\([^)]*\bor\b[^)]*\)", s, re.I)
        or re.search(r",\s*(?:[^,]+,\s*)*or\s+", s, re.I)
    )


def _split_list(line: str) -> list[str]:
    """Split a genuine "A, B, and C" enumeration; leave a single item whole."""
    if "," not in line:
        return [line]
    parts = [re.sub(r"^and\s+", "", p.strip(), flags=re.I) for p in line.split(",")]
    return [p for p in parts if p]


def _is_non_item(part: str) -> bool:
    low = part.lower().strip()
    if not low:
        return True
    if any(p in low for p in _NON_ITEM_PHRASES):
        return True
    base = re.sub(r"\b(as needed.*|to taste.*|for .*|if needed.*)$", "", low).strip()
    words = base.split()
    if words and all(w in _NON_ITEM_WORDS for w in words):
        return True
    return bool(base) and bool(_QTY_ONLY.match(base))


def parse_ingredient_lines(text: str) -> list[str]:
    """Split a pasted recipe/ingredient blob into clean, deduped item strings.

    Strips bullets/numbering, keeps quantities attached to their item ("170 g
    Greek yogurt"), collapses "whey, casein, pea, or soy" alternations to the
    first option, and drops headers ("Ingredients:") and non-items ("ice, and
    water as needed for thickness").
    """
    items: list[str] = []
    for raw in re.split(r"[\n\r;]+", text or ""):
        line = _BULLET.sub("", raw).strip()
        if not line or line.endswith(":"):
            continue
        if _has_alternation(line):
            cleaned = _clean(_first_alternative(line))
            if cleaned and not _is_non_item(cleaned):
                items.append(cleaned)
            continue
        for part in _split_list(line):
            cleaned = _clean(part)
            if cleaned and not _is_non_item(cleaned):
                items.append(cleaned)

    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        key = it.lower()
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def coerce_items(value) -> list[str]:
    """Accept a pasted string or an already-split list; return clean items."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [s for s in (str(v).strip() for v in value) if s]
    return parse_ingredient_lines(str(value))


def wholefoods_search_links(items: list[str]) -> str:
    """Per-item Whole Foods storefront search links, as a compact numbered list."""
    return "\n".join(
        f"{i}. {item}: {_WF_SEARCH.format(q=quote_plus(item))}"
        for i, item in enumerate(coerce_items(items), 1)
    )


# --------------------------------------------------------------------------- #
# Structured line items — Instacart wants {name, quantity, unit, displayText},
# and SILENTLY DROPS any line item missing quantity or unit, so both are always
# populated (defaulting 1 / "each"). displayText carries the verbatim line.
# --------------------------------------------------------------------------- #

# Unicode vulgar fractions -> decimal value ("½ scoop" -> 0.5).
_UNICODE_FRACTIONS = {
    "½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75,
    "⅕": 0.2, "⅖": 0.4, "⅗": 0.6, "⅘": 0.8, "⅙": 1 / 6, "⅚": 5 / 6,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
    "⅐": 1 / 7, "⅑": 1 / 9, "⅒": 0.1,
}
_FRAC_CHARS = "".join(_UNICODE_FRACTIONS)

# Measurement units recognized right after a quantity. Deliberately excludes
# vague amounts ("handful", "pinch") so "1 big handful spinach" stays unit=each.
_UNITS = {
    "cup", "cups", "tbsp", "tablespoon", "tablespoons", "tsp", "teaspoon",
    "teaspoons", "g", "gram", "grams", "kg", "mg", "oz", "ounce", "ounces",
    "lb", "lbs", "pound", "pounds", "ml", "l", "liter", "liters", "litre",
    "litres", "scoop", "scoops", "clove", "cloves", "can", "cans", "bunch",
    "bunches", "slice", "slices", "piece", "pieces", "stick", "sticks",
    "package", "packages", "pkg", "sprig", "sprigs", "head", "heads", "stalk",
    "stalks", "quart", "quarts", "pint", "pints", "gallon", "gallons",
}

_QTY_TOKEN = re.compile(
    r"^\s*("
    r"\d+\s+\d+/\d+"            # mixed: 1 1/2
    rf"|\d+\s*[{_FRAC_CHARS}]"  # mixed unicode: 1½ / 1 ½
    rf"|[{_FRAC_CHARS}]"        # bare unicode: ½
    r"|\d+/\d+"                 # fraction: 3/4
    r"|\d+\.\d+"               # decimal: 1.5
    r"|\d+"                    # integer: 170
    r")\s+"
)


def _qty_value(token: str) -> float:
    token = token.strip()
    for ch, val in _UNICODE_FRACTIONS.items():
        if ch in token:
            whole = token.replace(ch, "").strip()
            return round((float(whole) if whole else 0.0) + val, 4)
    if "/" in token:
        parts = token.split()
        num, den = parts[-1].split("/")
        whole = float(parts[0]) if len(parts) == 2 else 0.0
        return round(whole + float(num) / float(den), 4)
    return float(token)


def _tidy_number(q) -> float | int:
    q = float(q)
    return int(q) if q.is_integer() else round(q, 4)


def _structure_line(line: str) -> dict:
    """One cleaned ingredient line -> {name, quantity, unit, displayText}."""
    display = _clean(line)
    quantity: float = 1
    rest = display
    m = _QTY_TOKEN.match(display)
    if m:
        quantity = _qty_value(m.group(1))
        rest = display[m.end() :].strip() or display
    unit, name = "each", rest
    head, _, tail = rest.partition(" ")
    if head.lower().rstrip(".") in _UNITS and tail.strip():
        unit, name = head.lower().rstrip("."), tail.strip()
    return {
        "name": name,
        "quantity": _tidy_number(quantity),
        "unit": unit,
        "displayText": display,
    }


def parse_line_items(text: str) -> list[dict]:
    """Structured Instacart line items from a pasted recipe/list blob."""
    return [it for it in map(_structure_line, parse_ingredient_lines(text)) if it["name"]]


def _normalize_line_item(item: dict) -> dict:
    """Coerce a caller-supplied dict into the exact 4-key line-item shape."""
    name = str(item.get("name") or item.get("displayText") or "").strip()
    try:
        quantity = _tidy_number(item.get("quantity", 1) or 1)
    except (TypeError, ValueError):
        quantity = 1
    unit = str(item.get("unit") or "each").strip() or "each"
    display = str(item.get("displayText") or name).strip() or name
    return {"name": name, "quantity": quantity, "unit": unit, "displayText": display}


def coerce_line_items(value) -> list[dict]:
    """Accept a pasted blob, a list of strings, or ready-made line-item dicts."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            item = _normalize_line_item(v) if isinstance(v, dict) else _structure_line(str(v))
            if item["name"]:
                out.append(item)
        return out
    return parse_line_items(str(value))


def _as_steps(instructions) -> list[str]:
    if not instructions:
        return []
    if isinstance(instructions, str):
        return [s.strip() for s in re.split(r"[\n\r]+", instructions) if s.strip()]
    return [str(s).strip() for s in instructions if str(s).strip()]


def shopping_list_arguments(title: str, items) -> dict:
    """Build create-shopping-list arguments (title + lineItems). Pure/testable."""
    line_items = coerce_line_items(items)
    if not line_items:
        raise GroceryError("no items to add to the list")
    return {"title": (title or "Shopping list").strip(), "lineItems": line_items}


def recipe_arguments(title: str, ingredients, instructions=None) -> dict:
    """Build create-recipe arguments (title + ingredients [+ instructions])."""
    line_items = coerce_line_items(ingredients)
    if not (title or "").strip() or not line_items:
        raise GroceryError("a recipe needs a title and ingredients")
    args: dict = {"title": title.strip(), "ingredients": line_items}
    steps = _as_steps(instructions)
    if steps:
        args["instructions"] = steps
    return args


# --------------------------------------------------------------------------- #
# Instacart MCP client.
# --------------------------------------------------------------------------- #

_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)
_PREFERRED_KEYS = {
    "products_link_url",
    "shopping_list_url",
    "recipe_url",
    "share_url",
    "url",
    "link",
}


def _mcp_payload(tool_name: str, arguments: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
        "id": 1,
    }


def _parse_mcp_body(body: str, content_type: str = "") -> dict:
    """Decode a JSON-RPC response from either a JSON or an SSE body."""
    body = (body or "").strip()
    if not body:
        raise GroceryError("empty response from Instacart")

    looks_sse = "event-stream" in (content_type or "").lower() or body.startswith(
        ("event:", "data:", ":")
    )
    if not looks_sse:
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise GroceryError(f"non-JSON Instacart response: {exc}") from exc

    chunks = [
        line[len("data:") :].strip()
        for line in body.splitlines()
        if line.strip().startswith("data:")
    ]
    chunks = [c for c in chunks if c and c != "[DONE]"]
    # A single event may span multiple data: lines; also fall back to the last
    # standalone chunk that parses (servers often emit one JSON per event).
    for candidate in ["\n".join(chunks), *reversed(chunks)]:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise GroceryError("no JSON payload in Instacart event-stream")


def _find_url(obj) -> str | None:
    """Recursively pull a share URL out of the MCP result.

    Preference order: a value under a known link key, then any instacart.com URL
    found in free text, then any URL at all.
    """
    found: list[tuple[int, str]] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str) and k.lower() in _PREFERRED_KEYS and v.startswith("http"):
                    found.append((0, v))
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            for m in _URL_RE.findall(node):
                found.append((1 if "instacart.com" in m.lower() else 2, m))

    walk(obj)
    if not found:
        return None
    found.sort(key=lambda t: t[0])
    return found[0][1].rstrip(".,);")


def _extract_share_url(rpc: dict) -> str:
    if not isinstance(rpc, dict):
        raise GroceryError("unexpected Instacart response shape")
    err = rpc.get("error")
    if err:
        msg = err.get("message") if isinstance(err, dict) else err
        raise GroceryError(f"Instacart error: {msg}")
    url = _find_url(rpc.get("result", rpc))
    if not url:
        raise GroceryError("Instacart response contained no link")
    return url


async def _call_mcp(
    http: httpx.AsyncClient, api_key: str, tool_name: str, arguments: dict
) -> str:
    resp = await http.post(
        MCP_URL,
        json=_mcp_payload(tool_name, arguments),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json, text/event-stream",
        },
        timeout=30,
    )
    resp.raise_for_status()
    rpc = _parse_mcp_body(resp.text, resp.headers.get("content-type", ""))
    return _extract_share_url(rpc)


async def create_shopping_list(
    http: httpx.AsyncClient, api_key: str, title: str, items
) -> str:
    """Build an Instacart shopping-list page; return its shareable URL."""
    args = shopping_list_arguments(title, items)
    return await _call_mcp(http, api_key, "create-shopping-list", args)


async def create_recipe(
    http: httpx.AsyncClient,
    api_key: str,
    title: str,
    ingredients,
    instructions=None,
) -> str:
    """Build an Instacart recipe page; return its shareable URL."""
    args = recipe_arguments(title, ingredients, instructions)
    return await _call_mcp(http, api_key, "create-recipe", args)
