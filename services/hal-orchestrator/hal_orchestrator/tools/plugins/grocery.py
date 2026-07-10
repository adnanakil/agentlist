"""grocery tool — one tap-to-shop link from a recipe or shopping list.

First drop-in plugin: declaration, policy, timeout, and handler ship together
here. `list` (default) and `recipe` build an Instacart link (works with the
user's own local stores); `wholefoods_links` is the per-item Whole Foods
fallback for a user who insists on Whole Foods. The Instacart client and the
text parsing live in services/grocery.py.

Instacart's developer program stopped accepting applications (checked
2026-07-10; the old ~/.hal/.instacart_key is revoked — 401 on both MCP
environments), so until a key exists every Instacart action silently falls
back to Whole Foods search links. The Instacart path stays intact behind
INSTACART_API_KEY for whenever applications reopen.
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
        "Turn a recipe or shopping list into ONE tap-to-shop link. Whole "
        "Foods/Amazon has no cart you can fill directly, so LEAD with an "
        "Instacart link: it works with the user's own local stores (Wegmans, "
        "Costco, Key Food, etc.) and pre-fills everything for checkout. "
        "action=list (default): items (a pasted recipe/list blob or a list) + "
        "an optional title -> a shareable Instacart shopping-list link. "
        "action=recipe: title + ingredients (+ optional instructions) -> a "
        "shoppable Instacart recipe page. action=wholefoods_links: per-item "
        "Whole Foods storefront search links, ONLY when the user insists on "
        "Whole Foods specifically. Works in both DMs and group chats ('add "
        "this to our grocery list'). Always safe to call: when Instacart is "
        "unavailable the tool returns per-item Whole Foods search links "
        "instead — relay whichever reply it gives."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "recipe", "wholefoods_links"],
                "description": "Default list.",
            },
            "items": {
                "type": "string",
                "description": (
                    "The groceries — a pasted recipe/list blob or a comma/"
                    "newline-separated list. Used by list and wholefoods_links."
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
        else "I can't do a one-tap Instacart cart right now, so here's the "
        "next best thing — a Whole Foods search link per item, tap each to add it:"
    )
    return lead + "\n\n" + grocery.wholefoods_search_links(items)


async def tool_grocery(args: dict, ctx: ToolContext) -> str:
    action = (args.get("action") or "list").strip().lower()

    if action == "wholefoods_links":
        items = grocery.coerce_items(args.get("items"))
        if not items:
            return "Tell me the items and I'll pull up a Whole Foods search link for each."
        return _wholefoods_reply(items, insisted=True)

    api_key = (ctx.settings.instacart_api_key or "").strip()

    if action == "list":
        items = grocery.coerce_items(args.get("items"))
        if not items:
            return "What should go on the list? Send me the items or paste the recipe."
        if not api_key:
            log.info("grocery.no_key_fallback", items=len(items))
            return _wholefoods_reply(items)
        title = (args.get("title") or "Shopping list").strip() or "Shopping list"
        try:
            url = await grocery.create_shopping_list(ctx.http_client, api_key, title, items)
        except Exception as exc:
            log.warning("grocery.list_failed", error=str(exc), items=len(items))
            return _wholefoods_reply(items)
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
        timeout_seconds=30,
        parallel_safe=False,
    )
)
