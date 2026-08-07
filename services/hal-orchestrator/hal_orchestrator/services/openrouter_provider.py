"""OpenRouter provider — a Gemini-shaped shim over OpenRouter's OpenAI
chat-completions-compatible endpoint.

Same contract as claude_provider/glm_provider/openai_provider: translate
Gemini-format history (+ MAIN_TOOLS function_declarations) INTO a
/v1/chat/completions request, and translate the response BACK into a
Gemini-shaped dict, so routes/message.py stays provider-agnostic. Route a task
here by setting its model id to any OpenRouter "vendor/model" id (e.g.
GEMINI_MODEL=moonshotai/kimi-k3) — gemini.py:_dispatch_model sends any model id
containing "/" to call_openrouter; no native model id has one.

Verified empirically against moonshotai/kimi-k3:
- Fabricated positional tool_call ids are accepted — Gemini format pairs
  functionCall↔functionResponse by ORDER, so we regenerate deterministic ids
  on every translation (same trick as the Responses-API shim).
- Replaying assistant tool_calls WITHOUT the model's reasoning is accepted, so
  the shim is stateless: no `_claude_block` analog to stash, and the
  dispatcher always strips Claude-primary residue before calling here.
- The request body is deliberately LEAN (no `reasoning`, no `temperature`):
  reasoning models on OpenRouter think by default, and an unsupported param
  can null the whole response (same reason the GLM shim is lean).
  `thinking_level` is accepted for a uniform provider signature but unused.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import structlog

from ag_common.config import HalOrchestratorConfig

log = structlog.get_logger()

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_RETRYABLE = {429, 500, 502, 503}
_BACKOFF = [5, 10, 20]


# --------------------------------------------------------------------------- #
# Gemini → OpenRouter (chat completions)
# --------------------------------------------------------------------------- #


def _to_openrouter_tools(tools: list[dict] | None) -> list[dict]:
    """MAIN_TOOLS ([{function_declarations:[{name,description,parameters}]}]) →
    chat-completions tools ([{type:"function",function:{...}}] — NESTED, unlike
    the Responses API's flat shape). Declarations are already lowercase JSON
    Schema, so they carry over."""
    out: list[dict] = []
    for group in tools or []:
        for decl in group.get("function_declarations", []):
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": decl["name"],
                        "description": decl.get("description", ""),
                        "parameters": decl.get("parameters")
                        or {"type": "object", "properties": {}},
                    },
                }
            )
    return out


def _to_openrouter_messages(history: list[dict], system: str | None) -> list[dict]:
    """Gemini history → chat-completions messages. Assistant functionCall parts
    are BUFFERED until the following turn proves their outputs exist — the API
    400s on an assistant tool_calls message with no matching role:"tool"
    replies, and trimmed/loaded history can carry such danglers. Unmatched
    calls are dropped (the assistant's text, already emitted, carries the
    context); with fewer responses than calls, the matched prefix survives —
    ids are positional, so surviving pairs still line up."""
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    pending_calls: list[dict] = []  # tool_calls awaiting their tool replies
    pending_text: str = ""  # assistant text emitted alongside buffered calls

    for idx, turn in enumerate(history):
        parts = turn.get("parts", [])
        if turn.get("role") == "model":
            pending_calls = []
            # `_claude_block`-only parts (stashed thinking from a
            # Claude-primary turn) have no "text"/"functionCall" keys and fall
            # through both filters here.
            texts = [p["text"] for p in parts if p.get("text")]
            calls = [p["functionCall"] for p in parts if "functionCall" in p]
            if calls:
                pending_text = "\n".join(texts)
                pending_calls = [
                    {
                        "id": f"call_{idx}_{i}",
                        "type": "function",
                        "function": {
                            "name": fc.get("name", ""),
                            "arguments": json.dumps(fc.get("args") or {}),
                        },
                    }
                    for i, fc in enumerate(calls)
                ]
            elif texts:
                messages.append({"role": "assistant", "content": "\n".join(texts)})
        else:
            fn_responses = [p for p in parts if "functionResponse" in p]
            if fn_responses:
                # Pair to the buffered calls by order; emit the assistant
                # tool_calls message followed by its role:"tool" replies.
                # Orphaned responses (call side trimmed) and unmatched calls
                # (response side trimmed) are dropped.
                paired = list(zip(pending_calls, fn_responses, strict=False))
                if paired:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": pending_text,
                            "tool_calls": [call for call, _ in paired],
                        }
                    )
                    for call, p in paired:
                        fr = p["functionResponse"]
                        result = (fr.get("response") or {}).get("content", "")
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call["id"],
                                "content": str(result),
                            }
                        )
                pending_calls = []
                pending_text = ""
            else:
                pending_calls = []
                pending_text = ""
                content: list[dict] = [
                    {"type": "text", "text": p["text"]} for p in parts if p.get("text")
                ]
                images = False
                for p in parts:
                    if "inlineData" in p:
                        images = True
                        idata = p["inlineData"]
                        mime = idata.get("mimeType", "image/jpeg")
                        content.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime};base64,{idata.get('data', '')}"
                                },
                            }
                        )
                if content:
                    # Plain string when text-only; content-part list only for
                    # images (maximum provider compatibility).
                    if images:
                        messages.append({"role": "user", "content": content})
                    else:
                        messages.append(
                            {
                                "role": "user",
                                "content": "\n".join(c["text"] for c in content),
                            }
                        )

    return messages


# --------------------------------------------------------------------------- #
# OpenRouter → Gemini
# --------------------------------------------------------------------------- #


def _to_gemini_response(data: dict) -> dict | None:
    choices = data.get("choices") or []
    if not choices:
        return None
    msg = choices[0].get("message") or {}
    parts: list[dict] = []
    if msg.get("content"):
        parts.append({"text": msg["content"]})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except (ValueError, TypeError):
            args = {}
        parts.append({"functionCall": {"name": fn.get("name"), "args": args}})
    # `reasoning` on the message is skipped: replay isn't required (verified),
    # and nothing downstream can consume it.
    if not parts:
        return None
    finish_raw = choices[0].get("finish_reason")
    if any("functionCall" in p for p in parts):
        finish = "TOOL_CALLS"
    elif finish_raw == "length":
        finish = "MAX_TOKENS"
    else:
        finish = "STOP"
    return {"candidates": [{"content": {"parts": parts}, "finishReason": finish}]}


# --------------------------------------------------------------------------- #
# Call
# --------------------------------------------------------------------------- #


async def call_openrouter(
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
    """Run a Gemini-shaped request through any OpenRouter model. Returns a
    Gemini-shaped response dict (or None on failure), so call sites stay
    provider-agnostic. `thinking_level` is accepted for a uniform provider
    signature but unused — see module docstring."""
    if not settings.openrouter_api_key:
        log.error("openrouter.no_api_key")
        return None

    base = (settings.openrouter_base_url or DEFAULT_OPENROUTER_BASE_URL).rstrip("/")
    url = f"{base}/chat/completions"
    body: dict = {
        "model": model,
        "messages": _to_openrouter_messages(history, system),
        # Matched to the other providers' ceiling so a mid-turn failover never
        # halves the budget. Includes reasoning tokens on thinking models.
        "max_tokens": max_output_tokens or settings.gemini_max_output_tokens,
    }
    openrouter_tools = _to_openrouter_tools(tools)
    if openrouter_tools:
        body["tools"] = openrouter_tools

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    # A heavy agentic turn on a thinking model can run long; match the Claude
    # floor.
    timeout = max(settings.gemini_timeout_seconds, 180)

    for attempt in range(max_retries):
        try:
            resp = await client.post(url, headers=headers, json=body, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("error"):
                    # OpenRouter can 200 with an error body (moderation,
                    # upstream provider failure).
                    log.error("openrouter.response_error", error=str(data["error"])[:500])
                    return None
                u = data.get("usage") or {}
                log.info(
                    "openrouter.usage",
                    model=model,
                    input=u.get("prompt_tokens"),
                    cached=(u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                    reasoning=(u.get("completion_tokens_details") or {}).get(
                        "reasoning_tokens"
                    ),
                    output=u.get("completion_tokens"),
                    cost=u.get("cost"),
                )
                out = _to_gemini_response(data)
                if out is None:
                    log.error("openrouter.empty_output", body=str(data)[:500])
                return out
            if resp.status_code in _RETRYABLE and attempt < max_retries - 1:
                delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
                log.warning(
                    "openrouter.retryable", status=resp.status_code, attempt=attempt + 1
                )
                await asyncio.sleep(delay)
                continue
            log.error("openrouter.api_error", status=resp.status_code, body=resp.text[:500])
            return None
        except httpx.TimeoutException:
            log.error("openrouter.timeout", attempt=attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])
                continue
            return None
        except httpx.HTTPError as exc:
            log.error("openrouter.http_error", error=str(exc), attempt=attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])
                continue
            return None
    return None
