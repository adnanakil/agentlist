"""GLM (Z.ai) provider — a Gemini-shaped shim over Z.ai's Anthropic-compatible
endpoint.

Z.ai exposes an Anthropic `/v1/messages`-compatible API, so we REUSE the proven
Gemini<->Anthropic-format translators from claude_provider (the hard part:
tool_use id pairing, image blocks, role merging) and only change what's
provider-specific:

- base URL + auth: Z.ai's `glm_base_url`, the Z.ai key as `Authorization: Bearer`
  (their docs call it ANTHROPIC_AUTH_TOKEN).
- DROP the Anthropic-only knobs GLM's compat layer doesn't take — adaptive
  thinking (`thinking:{type:"adaptive"}`), `output_config.effort`, and
  `cache_control` blocks. (Same reason Haiku runs thinking-less in the Claude
  shim: sending an unsupported param nulls the whole response.)

Nothing in routes/message.py changes — it just sees `candidates[0].content.parts`.
Route a task here by setting its model id to `glm-*`; gemini.py:_dispatch_model
sends `glm-*` to call_glm and leaves every other model on its current path.
GLM's own response blocks are stashed as `_claude_block` by the shared
_to_gemini_response (so within-turn tool_use replay works); routes/message.py
already strips that key before persisting, so no new persistence logic is needed.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

from ag_common.config import HalOrchestratorConfig
from hal_orchestrator.services.claude_provider import (
    _to_anthropic_messages,
    _to_anthropic_tools,
    _to_gemini_response,
)

log = structlog.get_logger()

DEFAULT_GLM_BASE_URL = "https://api.z.ai/api/anthropic"
ANTHROPIC_VERSION = "2023-06-01"
_RETRYABLE = {429, 500, 502, 503, 529}
_BACKOFF = [5, 10, 20]


def _build_glm_body(
    history: list[dict],
    tools: list[dict] | None,
    system: str | None,
    model: str,
    max_output_tokens: int | None,
) -> dict:
    """Anthropic-shaped request body for Z.ai. Deliberately LEAN: no `thinking`,
    no `output_config`, no `cache_control` — GLM's compat endpoint doesn't take
    them, and an unsupported param can null the response. `system` is a plain
    string (NOT a cache_control block list)."""
    body: dict = {
        "model": model,
        "max_tokens": max_output_tokens or 16000,
        "messages": _to_anthropic_messages(history),
    }
    if system:
        body["system"] = system
    anthropic_tools = _to_anthropic_tools(tools)
    if anthropic_tools:
        body["tools"] = anthropic_tools
    return body


async def call_glm(
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
    """Run a Gemini-shaped request through a GLM model on Z.ai. Returns a
    Gemini-shaped response dict (or None on failure), so call sites stay
    provider-agnostic. `thinking_level` is accepted for a uniform provider
    signature but unused — GLM reasons by default."""
    if not settings.glm_api_key:
        log.error("glm.no_api_key")
        return None

    base = (settings.glm_base_url or DEFAULT_GLM_BASE_URL).rstrip("/")
    url = f"{base}/v1/messages"
    body = _build_glm_body(history, tools, system, model, max_output_tokens)
    headers = {
        # Z.ai's Anthropic-compatible endpoint authenticates the Z.ai key as a
        # bearer token (their ANTHROPIC_AUTH_TOKEN).
        "Authorization": f"Bearer {settings.glm_api_key}",
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    # GLM-5.2 + a heavy agentic turn can run long; match the Claude floor.
    timeout = max(settings.gemini_timeout_seconds, 180)

    for attempt in range(max_retries):
        try:
            resp = await client.post(url, headers=headers, json=body, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                u = data.get("usage") or {}
                log.info(
                    "glm.usage",
                    model=model,
                    input=u.get("input_tokens"),
                    cache_read=u.get("cache_read_input_tokens"),
                    output=u.get("output_tokens"),
                )
                return _to_gemini_response(data)
            if resp.status_code in _RETRYABLE and attempt < max_retries - 1:
                delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
                log.warning("glm.retryable", status=resp.status_code, attempt=attempt + 1)
                await asyncio.sleep(delay)
                continue
            log.error("glm.api_error", status=resp.status_code, body=resp.text[:500])
            return None
        except httpx.TimeoutException:
            log.error("glm.timeout", attempt=attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])
                continue
            return None

    return None
