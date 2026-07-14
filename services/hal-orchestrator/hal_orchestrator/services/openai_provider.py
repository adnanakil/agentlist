"""OpenAI (Responses API) provider — a Gemini-shaped shim.

Same contract as claude_provider/glm_provider: translate Gemini-format history
(+ MAIN_TOOLS function_declarations) INTO an OpenAI /v1/responses request, and
translate the response BACK into a Gemini-shaped dict, so routes/message.py
stays provider-agnostic — it just sees `candidates[0].content.parts`. Route a
task here by setting its model id to `gpt-*` (e.g. GEMINI_MODEL=gpt-5.6-luna).

Why /v1/responses and not /v1/chat/completions: gpt-5.6-luna REJECTS function
tools combined with reasoning_effort on chat completions ("use /v1/responses
or set reasoning_effort to 'none'") — and no-reasoning defeats the point of
running a frontier model. Verified empirically on the Responses API:
- `store: false` keeps it stateless (we replay full history every round, like
  every other provider here).
- Fabricated positional call_ids are accepted — Gemini format pairs
  functionCall↔functionResponse by ORDER, so we regenerate deterministic ids
  on every translation.
- Replaying function_call/function_call_output WITHOUT the model's reasoning
  items is accepted, so there is NO `_claude_block` analog to stash — the
  shim is stateless and Claude-primary residue is stripped by the dispatcher.
- Reasoning models reject `temperature`; depth goes in `reasoning.effort`
  (none/low/medium/high/xhigh). The main loop's depth comes from
  settings.openai_reasoning_effort (NOT gemini_thinking_level — see the config
  comment); an explicit per-call thinking_level (e.g. the watch poll forcing
  MINIMAL) still maps through so background work stays cheap if ever pointed
  at a gpt-* model.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import structlog

from ag_common.config import HalOrchestratorConfig

log = structlog.get_logger()

OPENAI_URL = "https://api.openai.com/v1/responses"
_RETRYABLE = {429, 500, 502, 503}
_BACKOFF = [5, 10, 20]


# --------------------------------------------------------------------------- #
# Gemini → OpenAI
# --------------------------------------------------------------------------- #


def _to_openai_tools(tools: list[dict] | None) -> list[dict]:
    """MAIN_TOOLS ([{function_declarations:[{name,description,parameters}]}]) →
    Responses-API tools ([{type:"function",name,description,parameters}] —
    FLAT, unlike chat completions' nested {function:{...}}). The declarations
    are already lowercase JSON Schema, so they carry over."""
    out: list[dict] = []
    for group in tools or []:
        for decl in group.get("function_declarations", []):
            out.append(
                {
                    "type": "function",
                    "name": decl["name"],
                    "description": decl.get("description", ""),
                    "parameters": decl.get("parameters")
                    or {"type": "object", "properties": {}},
                }
            )
    return out


def _to_openai_input(history: list[dict]) -> list[dict]:
    """Gemini history → Responses-API input items. functionCall items are
    BUFFERED until the following turn proves their outputs exist — the API
    400s on a function_call with no function_call_output, and trimmed/loaded
    history can carry such danglers. Unmatched calls are dropped (the
    assistant's text, already emitted, carries the context); with fewer
    responses than calls, the matched prefix survives — ids are positional,
    so the surviving pairs still line up."""
    items: list[dict] = []
    pending_calls: list[dict] = []  # function_call items awaiting their outputs

    for idx, turn in enumerate(history):
        parts = turn.get("parts", [])
        if turn.get("role") == "model":
            pending_calls = []
            # `_claude_block`-only parts (stashed thinking from a Claude-primary
            # turn) have no "text"/"functionCall" keys and fall through both
            # filters here.
            texts = [p["text"] for p in parts if p.get("text")]
            if texts:
                items.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "\n".join(texts)}],
                    }
                )
            for i, p in enumerate(fc for fc in parts if "functionCall" in fc):
                fc = p["functionCall"]
                pending_calls.append(
                    {
                        "type": "function_call",
                        "call_id": f"call_{idx}_{i}",
                        "name": fc.get("name", ""),
                        "arguments": json.dumps(fc.get("args") or {}),
                    }
                )
        else:
            fn_responses = [p for p in parts if "functionResponse" in p]
            if fn_responses:
                # Pair to the buffered calls by order; emit adjacent
                # call/output pairs. Orphaned responses (call side trimmed)
                # and unmatched calls (response side trimmed) are dropped.
                for call, p in zip(pending_calls, fn_responses, strict=False):
                    fr = p["functionResponse"]
                    result = (fr.get("response") or {}).get("content", "")
                    items.append(call)
                    items.append(
                        {
                            "type": "function_call_output",
                            "call_id": call["call_id"],
                            "output": str(result),
                        }
                    )
                pending_calls = []
            else:
                pending_calls = []
                content: list[dict] = [
                    {"type": "input_text", "text": p["text"]}
                    for p in parts
                    if p.get("text")
                ]
                for p in parts:
                    if "inlineData" in p:
                        idata = p["inlineData"]
                        mime = idata.get("mimeType", "image/jpeg")
                        content.append(
                            {
                                "type": "input_image",
                                "image_url": f"data:{mime};base64,{idata.get('data', '')}",
                            }
                        )
                if content:
                    items.append({"role": "user", "content": content})

    return items


def _effort_from_level(level: str | None) -> str | None:
    lvl = (level or "").strip().upper()
    return {
        "MINIMAL": "none",
        "LOW": "low",
        "MEDIUM": "medium",
        "HIGH": "high",
        "MAX": "xhigh",
    }.get(lvl)


# --------------------------------------------------------------------------- #
# OpenAI → Gemini
# --------------------------------------------------------------------------- #


def _to_gemini_response(data: dict) -> dict | None:
    parts: list[dict] = []
    for item in data.get("output") or []:
        t = item.get("type")
        if t == "message":
            text = "".join(
                c.get("text", "")
                for c in item.get("content") or []
                if c.get("type") == "output_text"
            )
            if text:
                parts.append({"text": text})
        elif t == "function_call":
            try:
                args = json.loads(item.get("arguments") or "{}")
            except (ValueError, TypeError):
                args = {}
            parts.append({"functionCall": {"name": item.get("name"), "args": args}})
        # "reasoning" items are skipped: replay isn't required (verified), and
        # nothing downstream can consume them.
    if not parts:
        return None
    if any("functionCall" in p for p in parts):
        finish = "TOOL_CALLS"
    elif (
        data.get("status") == "incomplete"
        and (data.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
    ):
        finish = "MAX_TOKENS"
    else:
        finish = "STOP"
    return {"candidates": [{"content": {"parts": parts}, "finishReason": finish}]}


# --------------------------------------------------------------------------- #
# Call
# --------------------------------------------------------------------------- #


async def call_openai(
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
    """Run a Gemini-shaped request through OpenAI. Returns a Gemini-shaped
    response dict (or None on failure), so call sites are provider-agnostic."""
    if not settings.openai_api_key:
        log.error("openai.no_api_key")
        return None

    body: dict = {
        "model": model,
        "store": False,  # stateless — full history replayed every round
        "input": _to_openai_input(history),
        # Ceiling for reasoning + visible output combined; matched to the other
        # providers' 16384 so a mid-turn failover never halves the budget.
        "max_output_tokens": max_output_tokens or settings.gemini_max_output_tokens,
    }
    if system:
        body["instructions"] = system
    effort = _effort_from_level(thinking_level) or settings.openai_reasoning_effort
    if effort:
        body["reasoning"] = {"effort": effort}
    openai_tools = _to_openai_tools(tools)
    if openai_tools:
        body["tools"] = openai_tools

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    # xhigh reasoning on a heavy agentic turn can run long.
    timeout = max(settings.gemini_timeout_seconds, 180)

    for attempt in range(max_retries):
        try:
            resp = await client.post(OPENAI_URL, headers=headers, json=body, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("error"):
                    log.error("openai.response_error", error=str(data["error"])[:500])
                    return None
                u = data.get("usage") or {}
                log.info(
                    "openai.usage",
                    model=model,
                    input=u.get("input_tokens"),
                    cached=(u.get("input_tokens_details") or {}).get("cached_tokens"),
                    reasoning=(u.get("output_tokens_details") or {}).get(
                        "reasoning_tokens"
                    ),
                    output=u.get("output_tokens"),
                )
                out = _to_gemini_response(data)
                if out is None:
                    log.error("openai.empty_output", body=str(data)[:500])
                return out
            if resp.status_code in _RETRYABLE and attempt < max_retries - 1:
                delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
                log.warning("openai.retryable", status=resp.status_code, attempt=attempt + 1)
                await asyncio.sleep(delay)
                continue
            log.error("openai.api_error", status=resp.status_code, body=resp.text[:500])
            return None
        except httpx.TimeoutException:
            log.error("openai.timeout", attempt=attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])
                continue
            return None
        except httpx.HTTPError as exc:
            log.error("openai.http_error", error=str(exc), attempt=attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])
                continue
            return None
    return None
