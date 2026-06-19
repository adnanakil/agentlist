"""Claude (Anthropic Messages API) provider — a Gemini-shaped shim.

HAL's whole loop is built on Gemini's wire format (history of {role, parts} with
text/functionCall/functionResponse; tools as function_declarations; responses as
candidates[].content.parts). This adapter lets the SAME loop run on Claude: it
translates Gemini-format history + tools INTO an Anthropic /v1/messages request,
and translates the Anthropic response BACK into a Gemini-shaped dict, so nothing
in routes/message.py has to change — it just sees `candidates[0].content.parts`.

Hard parts handled:
- Tool-call id pairing: Gemini matches functionCall↔functionResponse by ORDER;
  Anthropic needs tool_use.id ↔ tool_result.tool_use_id. We pair by order.
- Interleaved thinking (adaptive thinking auto-enables it on Opus 4.6): thinking
  blocks carry a signature and MUST be replayed unmodified across the tool loop.
  We stash the RAW Anthropic blocks inside the Gemini parts as `_claude_block`
  so replay is byte-identical. Turns WITHOUT a stashed block (loaded from the
  persisted Gemini-format DB) are sent text-only — their old tool exchanges are
  collapsed away, which is fine (the assistant's text replies carry the context).
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

from ag_common.config import HalOrchestratorConfig

log = structlog.get_logger()

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"  # verified working in the smoke test
_RETRYABLE = {429, 500, 503, 529}
_BACKOFF = [5, 10, 20]


# --------------------------------------------------------------------------- #
# Gemini → Anthropic
# --------------------------------------------------------------------------- #


def _to_anthropic_tools(tools: list[dict] | None) -> list[dict]:
    """MAIN_TOOLS ([{function_declarations:[{name,description,parameters}]}]) →
    Anthropic tools ([{name,description,input_schema}])."""
    out: list[dict] = []
    for group in tools or []:
        for decl in group.get("function_declarations", []):
            out.append(
                {
                    "name": decl["name"],
                    "description": decl.get("description", ""),
                    "input_schema": decl.get("parameters")
                    or {"type": "object", "properties": {}},
                }
            )
    return out


def _claude_native(turn: dict) -> bool:
    """A turn we produced from a Claude response (carries raw blocks for exact
    replay). Loaded/persisted turns lack these and go text-only."""
    return any("_claude_block" in p for p in turn.get("parts", []))


def _to_anthropic_messages(history: list[dict]) -> list[dict]:
    msgs: list[dict] = []
    # Tool_use ids emitted by the most recent assistant turn, in order — the
    # following user turn's functionResponses pair to these positionally.
    pending_ids: list[str] = []

    for turn in history:
        role = "assistant" if turn.get("role") == "model" else "user"
        parts = turn.get("parts", [])
        blocks: list[dict] = []

        if role == "assistant" and _claude_native(turn):
            ids: list[str] = []
            for p in parts:
                raw = p.get("_claude_block")
                if raw is not None:
                    blocks.append(raw)
                    if raw.get("type") == "tool_use":
                        ids.append(raw["id"])
                elif "text" in p and p["text"]:
                    blocks.append({"type": "text", "text": p["text"]})
            pending_ids = ids
        elif role == "assistant":
            # Loaded assistant turn — text only (drop any functionCall).
            for p in parts:
                if "text" in p and p["text"]:
                    blocks.append({"type": "text", "text": p["text"]})
            pending_ids = []
        else:
            # User turn: either the real message (text/images) or tool_results.
            fn_responses = [p for p in parts if "functionResponse" in p]
            if fn_responses:
                # Pair to the preceding assistant turn's tool_use ids by order.
                for i, p in enumerate(fn_responses):
                    if i >= len(pending_ids):
                        break  # orphaned (loaded turn) — skip
                    fr = p["functionResponse"]
                    result = (fr.get("response") or {}).get("content", "")
                    blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": pending_ids[i],
                            "content": str(result),
                        }
                    )
                pending_ids = []
            else:
                for p in parts:
                    if "text" in p and p["text"]:
                        blocks.append({"type": "text", "text": p["text"]})
                    elif "inlineData" in p:
                        idata = p["inlineData"]
                        blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": idata.get("mimeType", "image/jpeg"),
                                    "data": idata.get("data", ""),
                                },
                            }
                        )

        if blocks:
            msgs.append({"role": role, "content": blocks})

    # Merge consecutive same-role messages (skipping turns above can leave two
    # user/assistant turns adjacent, which Anthropic rejects).
    merged: list[dict] = []
    for m in msgs:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"].extend(m["content"])
        else:
            merged.append(m)
    # Anthropic requires the first message to be from the user.
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    return merged


def _effort_from_level(level: str | None) -> str | None:
    lvl = (level or "").strip().upper()
    return {
        "MINIMAL": "low",
        "LOW": "low",
        "MEDIUM": "medium",
        "HIGH": "high",
        "MAX": "max",
    }.get(lvl)


def _supports_adaptive_thinking(model: str) -> bool:
    """Adaptive thinking (`thinking:{type:"adaptive"}` + `output_config.effort`)
    is an Opus/Sonnet-4.6+ / Fable / Mythos feature. Haiku 4.5 REJECTS it with a
    400 ("adaptive thinking is not supported on this model"), which nulls the
    whole response — so a cheap Haiku background model would silently return
    empty. Gate the param by family so Haiku (and any future non-thinking model)
    runs thinking-less instead of erroring."""
    return "haiku" not in (model or "").lower()


# --------------------------------------------------------------------------- #
# Anthropic → Gemini
# --------------------------------------------------------------------------- #

_STOP_MAP = {
    "tool_use": "TOOL_CALLS",
    "end_turn": "STOP",
    "stop_sequence": "STOP",
    "max_tokens": "MAX_TOKENS",
    "refusal": "REFUSAL",
    "pause_turn": "STOP",
}


def _to_gemini_response(data: dict) -> dict:
    parts: list[dict] = []
    for b in data.get("content", []):
        t = b.get("type")
        if t == "text":
            parts.append({"text": b.get("text", "")})
        elif t == "thinking":
            # Stash the raw block so we can replay it byte-identical (signature
            # intact). No "text" key → the loop's reply/text extraction skips it.
            parts.append({"_claude_block": b})
        elif t == "redacted_thinking":
            parts.append({"_claude_block": b})
        elif t == "tool_use":
            parts.append(
                {
                    "functionCall": {"name": b.get("name"), "args": b.get("input") or {}},
                    "_claude_block": b,
                }
            )
    finish = _STOP_MAP.get(data.get("stop_reason"), data.get("stop_reason"))
    return {"candidates": [{"content": {"parts": parts}, "finishReason": finish}]}


# --------------------------------------------------------------------------- #
# Call
# --------------------------------------------------------------------------- #


async def call_claude(
    client: httpx.AsyncClient,
    settings: HalOrchestratorConfig,
    history: list[dict],
    tools: list[dict] | None,
    system: str | None,
    model: str,
    max_retries: int,
    max_output_tokens: int | None,
    thinking_level: str | None,
) -> dict | None:
    """Run a Gemini-shaped request through Claude. Returns a Gemini-shaped
    response dict (or None on failure), so call sites are provider-agnostic."""
    if not settings.anthropic_api_key:
        log.error("claude.no_api_key")
        return None

    messages = _to_anthropic_messages(history)
    body: dict = {
        "model": model,
        "max_tokens": max_output_tokens or 16000,
        "messages": messages,
    }
    # Adaptive thinking + effort only on models that support it (Opus/Sonnet
    # 4.6+/Fable). Haiku 4.5 400s on `thinking:adaptive` → null response, so it
    # runs thinking-less. (Lets a cheap Haiku carry the background machinery.)
    if _supports_adaptive_thinking(model):
        body["thinking"] = {"type": "adaptive"}
        effort = _effort_from_level(thinking_level or settings.gemini_thinking_level)
        if effort:
            body["output_config"] = {"effort": effort}
    # --- Prompt caching (cost) ------------------------------------------------
    # HAL re-sends a large fixed prefix on every tool round: a ~6k-token static
    # system prompt (+ profile/playbook/summary) and ~12k tokens of history.
    # Without cache_control each round re-pays full input price for all of it; a
    # heavy 22-round turn pays it 22×. Mark the stable regions so rounds 2..N
    # (and bursts within the 5-min TTL) read the prefix at 0.1× instead.
    if system:
        # Pass system as a block list (not a bare string) so we can attach
        # cache_control. Caches tools+system together (tools precede system).
        body["system"] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
    anthropic_tools = _to_anthropic_tools(tools)
    if anthropic_tools:
        body["tools"] = anthropic_tools
    # Cache the history prefix too: mark the last content block of the last
    # message. As the agentic loop appends rounds, Anthropic extends the cache
    # incrementally — read the cached prefix, write only the new tail.
    if messages and isinstance(messages[-1].get("content"), list) and messages[-1]["content"]:
        tail = messages[-1]["content"][-1]
        if isinstance(tail, dict):
            tail["cache_control"] = {"type": "ephemeral"}

    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    # Opus 4.6 + thinking on a heavy agentic turn can run long.
    timeout = max(settings.gemini_timeout_seconds, 180)

    for attempt in range(max_retries):
        try:
            resp = await client.post(ANTHROPIC_URL, headers=headers, json=body, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                u = data.get("usage") or {}
                # cache_read >> cache_write across a turn = caching is working.
                log.info(
                    "claude.usage",
                    model=model,
                    input=u.get("input_tokens"),
                    cache_write=u.get("cache_creation_input_tokens"),
                    cache_read=u.get("cache_read_input_tokens"),
                    output=u.get("output_tokens"),
                )
                return _to_gemini_response(data)
            if resp.status_code in _RETRYABLE and attempt < max_retries - 1:
                delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
                log.warning("claude.retryable", status=resp.status_code, attempt=attempt + 1)
                await asyncio.sleep(delay)
                continue
            log.error("claude.api_error", status=resp.status_code, body=resp.text[:500])
            return None
        except httpx.TimeoutException:
            log.error("claude.timeout", attempt=attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])
                continue
            return None
        except httpx.HTTPError as exc:
            log.error("claude.http_error", error=str(exc), attempt=attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])
                continue
            return None
    return None
