"""Per-model pricing for the eval suite's cost reports.

Prices are USD per 1M tokens (standard tier, no batch discount), split into
input / cached-read / output. Sources, verified 2026-07-13:

- OpenAI (gpt-5.6-luna, gpt-5.4, gpt-5.4-mini):
  https://developers.openai.com/api/docs/pricing — cached input bills at 10%
  of standard input on every listed model.
- Anthropic (claude-fable-5, claude-opus-4-8, claude-sonnet-5,
  claude-haiku-4-5): the claude-api skill's model table (cached 2026-06-24;
  matches https://platform.claude.com/docs/en/pricing.md). Cache reads bill at
  0.1x input; cache WRITES bill at 1.25x input (5-minute TTL — what the
  orchestrator's shim uses). claude-sonnet-5 has intro pricing ($2.00/$10.00)
  through 2026-08-31; the table carries the standard $3.00/$15.00 so
  projections don't understate costs after the intro lapses.
- Google (gemini-3.5-flash, for when the Gemini account is refunded):
  https://ai.google.dev/gemini-api/docs/pricing ($1.50/$0.15/$9.00).

Billing semantics baked into cost_of():
- `reasoning` tokens (OpenAI Responses reasoning, Anthropic thinking) are a
  SUBSET of `output` in every provider's usage report — they bill at the
  output rate and are already counted there. cost_of() deliberately ignores
  the field; billing it would double-count.
- `cache_write` (Anthropic cache_creation_input_tokens) bills at 1.25x input.
  OpenAI/Gemini report no separate write tier at these endpoints (0-cost
  entry keeps the math uniform).
"""

from __future__ import annotations

# model -> (input, cached_read, output, cache_write) USD per 1M tokens
PRICES: dict[str, tuple[float, float, float, float]] = {
    # gpt-5.6 is a three-tier family: sol (flagship), terra (mid), luna
    # (economy). Tier prices verified on developers.openai.com 2026-07-13;
    # cached input at the standard OpenAI 10% of input.
    "gpt-5.6-sol": (5.00, 0.50, 30.00, 0.0),
    "gpt-5.6-terra": (2.50, 0.25, 15.00, 0.0),
    "gpt-5.6-luna": (1.00, 0.10, 6.00, 0.0),
    "gpt-5.4": (2.50, 0.25, 15.00, 0.0),
    "gpt-5.4-mini": (0.75, 0.075, 4.50, 0.0),
    "claude-fable-5": (10.00, 1.00, 50.00, 12.50),
    "claude-opus-4-8": (5.00, 0.50, 25.00, 6.25),
    "claude-sonnet-5": (3.00, 0.30, 15.00, 3.75),
    "claude-haiku-4-5": (1.00, 0.10, 5.00, 1.25),
    "gemini-3.5-flash": (1.50, 0.15, 9.00, 0.0),
}


def has_pricing(model: str) -> bool:
    return model in PRICES


def cost_of(usage: dict, model: str) -> float:
    """USD cost of one turn's usage: {input, cached, output, reasoning?,
    cache_write?}. Missing/None fields count as 0. `reasoning` is ignored —
    it's a subset of `output` (see module docstring)."""
    if model not in PRICES:
        raise KeyError(
            f"No pricing for model {model!r} — add it to evals/pricing.py PRICES"
        )
    inp, cached, out, cache_write = PRICES[model]

    def tok(key: str) -> float:
        v = usage.get(key)
        return float(v) if v else 0.0

    return (
        tok("input") * inp
        + tok("cached") * cached
        + tok("output") * out
        + tok("cache_write") * cache_write
    ) / 1_000_000
