"""grocery tool — one tap-to-shop link from a recipe or shopping list.

First drop-in plugin: declaration, policy, timeout, and handler ship together
here. `list` (default) leads with an Instacart link when a key exists; without
one it builds a single Amazon add-to-cart link for the shippable items and
Whole Foods search links for the fresh ones. `amazon_cart` forces the Amazon
route for everything; `recipe` builds an Instacart recipe page; `wholefoods_links`
is the per-item Whole Foods fallback. The clients and parsing live in
services/grocery.py.

Instacart's developer program stopped accepting applications (checked
2026-07-10; the old ~/.hal/.instacart_key is revoked — 401 on both MCP
environments), so until a key exists the list action falls back to the Amazon
cart split. The Instacart path stays intact behind INSTACART_API_KEY for
whenever applications reopen.
"""

from __future__ import annotations

import structlog

from hal_orchestrator.services import grocery
from hal_orchestrator.tools.registry import ToolContext
from hal_orchestrator.tools.specs import ToolSpec, register_tool

log = structlog.get_logger()

_DECLARATION = {
    "name": "grocery",
    "description": (
        "Turn a recipe or shopping list into ONE tap-to-shop link. "
        "action=list (default): items (a pasted recipe/list blob or a list) -> "
        "ONE tappable link that fills the user's real Amazon cart with the "
        "shippable items (they may be asked to sign in to Amazon once, then the "
        "items carry through), plus Whole Foods search links for the fresh/"
        "perishable items. (If an Instacart key is configured it leads with an "
        "Instacart list instead.) action=amazon_cart: put EVERYTHING through the "
        "Amazon cart link (use for 'add these to my Amazon cart'), Whole Foods "
        "links only for anything not found. action=recipe: title + ingredients "
        "(+ optional instructions) -> a shoppable recipe page. "
        "action=wholefoods_links: per-item Whole Foods storefront search links, "
        "ONLY when the user insists on Whole Foods specifically. Works in both "
        "DMs and group chats ('add this to our grocery list'). Always safe to "
        "call — it degrades to search links, never an error; relay whichever "
        "reply it gives."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "amazon_cart", "recipe", "wholefoods_links"],
                "description": "Default list.",
            },
            "items": {
                "type": "string",
                "description": (
                    "The groceries — a pasted recipe/list blob or a comma/"
                    "newline-separated list. Used by list, amazon_cart, and "
                    "wholefoods_links."
                ),
            },
            "title": {
                "type": "string",
                "description": "Name for the list or recipe page (e.g. 'Smoothie run').",
            },
            "ingredients": {
                "type": "string",
                "description": "For action=recipe: the ingredient lines.",
            },
            "instructions": {
                "type": "string",
                "description": "For action=recipe: optional prep steps.",
            },
        },
    },
}


def _wholefoods_reply(items: list[str], insisted: bool = False) -> str:
    lead = (
        "Whole Foods doesn't let me fill a cart directly, so here are Whole "
        "Foods storefront search links — tap each to add it:"
        if insisted
        else "I couldn't match these on Amazon, so here's the next best thing — "
        "a Whole Foods search link per item, tap each to add it:"
    )
    return lead + "\n\n" + grocery.wholefoods_search_links(items)


def _amazon_cart_block(cart_pairs, associate_tag: str) -> str:
    n = len(cart_pairs)
    return (
        f"Tap once to fill your Amazon cart ({n} item{'s' if n != 1 else ''}):\n"
        f"{grocery.amazon_cart_url(cart_pairs, associate_tag=associate_tag)}\n"
        "(You may be asked to sign in to Amazon once — the items carry through.)"
    )


async def _discover_buckets(items: list[str], ctx: ToolContext, *, route_perishables: bool):
    """Split items into (cart_pairs, fresh, misses) via ASIN discovery.

    Perishables (when routing) skip discovery and go straight to `fresh`;
    everything else is searched — a hit becomes an (asin, qty) cart pair, a
    miss goes to `misses`.
    """
    to_discover: list[str] = []
    fresh: list[str] = []
    for it in items:
        (fresh if route_perishables and grocery.is_perishable(it) else to_discover).append(it)

    found = await grocery.discover_asins(ctx, to_discover) if to_discover else {}
    cart_pairs: list[tuple[str, int]] = []
    misses: list[str] = []
    for it in to_discover:
        cand = found.get(it)
        if cand:
            cart_pairs.append((cand.asin, grocery.cart_quantity(it)))
        else:
            misses.append(it)
    return cart_pairs, fresh, misses


async def _list_reply(items: list[str], ctx: ToolContext) -> str:
    """No-Instacart-key list reply: Amazon cart for shippables, WF for fresh,
    an honest line for anything found nowhere. All-WF fallback if nothing hits."""
    cart_pairs, fresh, misses = await _discover_buckets(items, ctx, route_perishables=True)
    if not cart_pairs:
        log.info("grocery.amazon_no_hits", items=len(items))
        return _wholefoods_reply(items)

    tag = (getattr(ctx.settings, "amazon_associate_tag", "") or "").strip()
    log.info(
        "grocery.amazon_split", cart=len(cart_pairs), fresh=len(fresh), misses=len(misses)
    )
    blocks = [_amazon_cart_block(cart_pairs, tag)]
    if fresh:
        blocks.append(
            "Fresh stuff ships better from Whole Foods — tap each to add:\n"
            + grocery.wholefoods_search_links(fresh)
        )
    if misses:
        names = ", ".join(grocery.item_label(m) for m in misses)
        blocks.append(f"Couldn't pin these on Amazon: {names}.")
    return "\n\n".join(blocks)


async def _amazon_cart_reply(items: list[str], ctx: ToolContext) -> str:
    """Everything through Amazon discovery (no perishable routing); WF links for
    misses. All-WF fallback if nothing hits."""
    cart_pairs, _fresh, misses = await _discover_buckets(items, ctx, route_perishables=False)
    if not cart_pairs:
        log.info("grocery.amazon_no_hits", items=len(items))
        return _wholefoods_reply(items)

    tag = (getattr(ctx.settings, "amazon_associate_tag", "") or "").strip()
    log.info("grocery.amazon_cart", cart=len(cart_pairs), misses=len(misses))
    blocks = [_amazon_cart_block(cart_pairs, tag)]
    if misses:
        blocks.append(
            "These weren't on Amazon — Whole Foods search links instead:\n"
            + grocery.wholefoods_search_links(misses)
        )
    return "\n\n".join(blocks)


async def tool_grocery(args: dict, ctx: ToolContext) -> str:
    action = (args.get("action") or "list").strip().lower()

    if action == "wholefoods_links":
        items = grocery.coerce_items(args.get("items"))
        if not items:
            return "Tell me the items and I'll pull up a Whole Foods search link for each."
        return _wholefoods_reply(items, insisted=True)

    if action == "amazon_cart":
        items = grocery.coerce_items(args.get("items"))
        if not items:
            return "Send me the items and I'll build one Amazon cart link."
        return await _amazon_cart_reply(items, ctx)

    api_key = (ctx.settings.instacart_api_key or "").strip()

    if action == "list":
        items = grocery.coerce_items(args.get("items"))
        if not items:
            return "What should go on the list? Send me the items or paste the recipe."
        if not api_key:
            return await _list_reply(items, ctx)
        title = (args.get("title") or "Shopping list").strip() or "Shopping list"
        try:
            url = await grocery.create_shopping_list(ctx.http_client, api_key, title, items)
        except Exception as exc:
            log.warning("grocery.list_failed", error=str(exc), items=len(items))
            return await _list_reply(items, ctx)
        n = len(items)
        return (
            f"Here's your Instacart list ({n} item{'s' if n != 1 else ''}):\n\n"
            f"{url}\n\n"
            "Tap it, pick your store, and it's all in the cart ready to check out."
        )

    if action == "recipe":
        title = (args.get("title") or "").strip()
        ingredients = grocery.coerce_items(args.get("ingredients") or args.get("items"))
        if not title or not ingredients:
            return "For a recipe page I need a title and the ingredients."
        if not api_key:
            log.info("grocery.no_key_fallback", items=len(ingredients))
            return _wholefoods_reply(ingredients)
        try:
            url = await grocery.create_recipe(
                ctx.http_client, api_key, title, ingredients, args.get("instructions")
            )
        except Exception as exc:
            log.warning("grocery.recipe_failed", error=str(exc), title=title[:60])
            return _wholefoods_reply(ingredients)
        return (
            f"Here's a shoppable recipe page for {title}:\n\n{url}\n\n"
            "Tap it, pick your store, and add every ingredient at once."
        )

    return f"Unknown grocery action: {action}. Use: list, recipe, wholefoods_links."


register_tool(
    ToolSpec(
        name="grocery",
        declaration=_DECLARATION,
        handler="hal_orchestrator.tools.plugins.grocery:tool_grocery",
        scopes=frozenset({"dm", "group"}),
        risk="write",
        timeout_seconds=60,  # covers the concurrent ASIN search batch
        parallel_safe=False,
    )
)
