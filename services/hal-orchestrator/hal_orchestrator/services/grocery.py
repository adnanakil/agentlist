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

import asyncio
import json
import re
from dataclasses import dataclass
from urllib.parse import quote_plus, urlencode

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
# Amazon add-to-cart — one tappable link that fills the user's real cart.
#
# Amazon has no cart API, but its documented remote "Add to Cart" form still
# works: /gp/aws/cart/add.html?ASIN.1=..&Quantity.1=.. redirects (through a
# sign-in if needed) to a cart pre-filled with every item. We find one ASIN per
# non-perishable item via web search, build that link, and route fresh/
# perishable items to Whole Foods search links instead (shipping fresh food
# from a warehouse is the wrong outcome). All the parsing/scoring below is pure
# and unit-tested; only discover_asins touches the network.
# --------------------------------------------------------------------------- #

_CART_ADD_URL = "https://www.amazon.com/gp/aws/cart/add.html"

# An Amazon ASIN is exactly 10 uppercase alphanumerics, in a /dp/ or
# /gp/product/ path segment. The trailing lookahead rejects 9-char and
# >10-char near-misses; [A-Z0-9] rejects lowercase.
_ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?![A-Z0-9])")

_WORD_RE = re.compile(r"[a-z0-9]+")
# Tokens that carry no product signal — dropped before overlap scoring.
_SCORE_STOP = {
    "the", "a", "an", "of", "and", "or", "with", "for", "to", "in", "on",
    "organic", "natural", "pack", "count", "ct", "oz", "lb", "lbs", "g", "kg",
    "ml", "l", "size", "value", "premium", "brand", "amazon", "com",
}

# "2 x eggs" / "3× cans" — the only pattern that maps to an Amazon unit count.
# A grocery amount ("170 g", "1 tbsp") is NOT a unit count and stays quantity 1.
_MULTIPLIER_RE = re.compile(r"^\s*(\d{1,2})\s*(?:x|×|\*)\s+", re.I)

# Perishable / fresh terms that belong at Whole Foods, matched as whole words
# (plural forms enumerated) so pantry-stable "peanut butter" / plant milks fall
# through to Amazon discovery. "frozen"/"fresh" are matched anywhere.
_PERISHABLE_WORDS = {
    "milk", "yogurt", "yoghurt", "cheese", "cream", "egg", "eggs", "butter",
    "spinach", "lettuce", "kale", "arugula", "greens", "cilantro", "parsley",
    "basil", "herb", "herbs", "tomato", "tomatoes", "cucumber", "avocado",
    "banana", "bananas", "berry", "berries", "blueberry", "blueberries",
    "strawberry", "strawberries", "raspberry", "raspberries", "blackberry",
    "blackberries", "grape", "grapes", "apple", "apples", "orange", "oranges",
    "lemon", "lemons", "lime", "limes", "carrot", "carrots", "onion", "onions",
    "garlic", "ginger", "celery", "broccoli", "cauliflower", "zucchini",
    "mushroom", "mushrooms", "potato", "potatoes", "chicken", "beef", "pork",
    "turkey", "fish", "salmon", "shrimp", "meat", "tofu", "hummus", "salad",
    "produce", "scallion", "scallions", "melon", "peach", "peaches", "mango",
    "mangoes", "pear", "pears", "grapefruit", "cabbage", "asparagus",
}
_PERISHABLE_ANYWHERE = ("frozen", "fresh")
# Nut/seed butters and plant milks are shelf-stable — keep them on Amazon.
_PANTRY_OVERRIDE = (
    "peanut butter", "almond butter", "cashew butter", "sunflower butter",
    "seed butter", "nut butter", "apple butter", "cocoa butter",
    "coconut butter", "soy milk", "almond milk", "oat milk", "coconut milk",
    "rice milk", "cashew milk", "shelf-stable", "powdered milk", "milk powder",
)


@dataclass
class AsinCandidate:
    """One Amazon product matched to a grocery item, with its overlap score."""

    asin: str
    title: str
    url: str
    score: float


def _tokens(text: str) -> list[str]:
    """Lowercased content tokens (stopwords dropped, trailing plural 's' folded)."""
    out = []
    for tok in _WORD_RE.findall((text or "").lower()):
        if tok in _SCORE_STOP or len(tok) < 2:
            continue
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


def extract_asins(url: str) -> list[str]:
    """Every ASIN embedded in an Amazon product URL (/dp/ or /gp/product/)."""
    return _ASIN_RE.findall(url or "")


def score_candidate(item_name: str, title: str, url: str) -> float:
    """Score how well a search hit's title matches the item (higher = better).

    Base is the fraction of the item's tokens present in the title; a canonical
    /dp/ URL gets a small bonus, and a missing head noun (obvious mismatch) a
    penalty so unrelated products score at or below zero.
    """
    item_toks = _tokens(item_name)
    if not item_toks:
        return 0.0
    title_toks = set(_tokens(title))
    overlap = sum(1 for t in set(item_toks) if t in title_toks)
    score = overlap / len(set(item_toks))
    if "/dp/" in (url or ""):
        score += 0.1
    if item_toks[-1] not in title_toks:  # head noun absent -> likely wrong item
        score -= 0.3
    return round(score, 4)


def best_asin_candidate(item_name: str, results: list[dict]) -> AsinCandidate | None:
    """Highest-scoring ASIN candidate across a list of {title, url} hits."""
    best: AsinCandidate | None = None
    for r in results or []:
        url, title = r.get("url", ""), r.get("title", "")
        for asin in extract_asins(url):
            cand = AsinCandidate(asin, title, url, score_candidate(item_name, title, url))
            if best is None or cand.score > best.score:
                best = cand
    if best is None or best.score <= 0:
        return None
    return best


def cart_quantity(item: str) -> int:
    """Amazon unit count for an item — always 1 unless it clearly says '2 x …'."""
    m = _MULTIPLIER_RE.match(item or "")
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 12 else 1
    return 1


def is_perishable(item: str) -> bool:
    """True for fresh/perishable items that should go to Whole Foods, not a
    ship-from-warehouse Amazon cart."""
    low = (item or "").lower()
    if any(p in low for p in _PANTRY_OVERRIDE):
        return False
    if any(p in low for p in _PERISHABLE_ANYWHERE):
        return True
    words = set(_WORD_RE.findall(low))
    return bool(words & _PERISHABLE_WORDS)


def item_label(item: str) -> str:
    """A short human label for an item — its name minus a leading quantity/unit
    ("1 tsp psyllium (not a heap)" -> "psyllium (not a heap)"). For prose."""
    return _structure_line(item)["name"] or _clean(item)


def amazon_cart_url(pairs, associate_tag: str = "") -> str:
    """Build the remote add-to-cart URL from (asin, quantity) pairs.

    Indexed ASIN.n / Quantity.n params per Amazon's documented form; the
    optional AssociateTag is appended only when a tag is configured.
    """
    params: list[tuple[str, str]] = []
    for i, (asin, qty) in enumerate(pairs, 1):
        params.append((f"ASIN.{i}", str(asin)))
        params.append((f"Quantity.{i}", str(int(qty) if qty else 1)))
    if associate_tag:
        params.append(("AssociateTag", associate_tag))
    return f"{_CART_ADD_URL}?{urlencode(params)}"


async def discover_asins(ctx, items, *, concurrency: int = 4, timeout: float = 8.0) -> dict:
    """Map each item -> best AsinCandidate (or None) via one web search each.

    Runs searches concurrently (bounded) with a per-search timeout so the whole
    batch fits the tool budget. An empty/failed/timed-out search is ROUTINE —
    that item maps to None and the caller sends it to Whole Foods instead. Never
    raises. `ctx` must expose `.http_client` and `.settings` (a ToolContext).
    """
    from hal_orchestrator.tools.web_search import search_web

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(item: str):
        async with sem:
            try:
                async with asyncio.timeout(timeout):
                    res = await search_web(f"amazon.com {item}", ctx, count=5)
            except Exception:
                log.warning("grocery.discover_search_failed", item=item[:60])
                return item, None
            return item, best_asin_candidate(item, res.results)

    found = await asyncio.gather(*(_one(it) for it in items))
    return dict(found)


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
