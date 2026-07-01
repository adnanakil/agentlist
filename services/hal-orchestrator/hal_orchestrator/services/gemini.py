"""Gemini API client — async HTTP calls with retry logic."""

from __future__ import annotations

import asyncio
import time

import httpx
import structlog

from ag_common.config import HalOrchestratorConfig

log = structlog.get_logger()

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Retryable HTTP status codes
RETRYABLE_STATUSES = {429, 500, 502, 503}

# --- Main-loop provider failover -------------------------------------------- #
# If the MAIN model (settings.gemini_model) fails, fall over through
# settings.model_fallbacks so one provider/model being down (Anthropic 529
# Overloaded, depleted credits) doesn't take HAL down. After the primary fails
# hard we skip it for a short cooldown so a sustained outage doesn't re-pay its
# retry tax every round. Module-global = process-wide (a provider outage hits
# every silo, so sharing the breaker is correct).
_primary_cooldown_until = 0.0
_PRIMARY_COOLDOWN_S = 90.0


def _fallback_chain(settings: HalOrchestratorConfig) -> list[str]:
    return [m.strip() for m in (settings.model_fallbacks or "").split(",") if m.strip()]


def _strip_claude_blocks(history: list[dict]) -> list[dict]:
    """Drop Claude-only raw blocks (`_claude_block` — thinking/tool_use with the
    primary model's signatures) so a DIFFERENT model can consume a history
    carrying primary-model turns (mid-turn failover). Native Gemini can't read
    them; a different Claude model would silently ignore them but still bill the
    tokens. Pure-thinking parts vanish; functionCall/text keep visible content."""
    out: list[dict] = []
    for turn in history:
        parts = []
        for p in turn.get("parts", []):
            if "_claude_block" in p:
                clean = {k: v for k, v in p.items() if k != "_claude_block"}
                if clean:
                    parts.append(clean)
            else:
                parts.append(p)
        if parts:
            out.append({"role": turn.get("role"), "parts": parts})
    return out


async def _dispatch_model(
    client, settings, history, tools, system, model,
    max_retries, max_output_tokens, thinking_level, *, is_primary: bool,
) -> dict | None:
    """Run one request on one model: claude-* via the Anthropic shim, glm-* via
    the Z.ai (Anthropic-compatible) shim, else the native Gemini path. A
    non-primary model gets the primary's raw provider blocks stripped (they're
    model-specific — a different model would mis-replay them)."""
    if model.startswith("claude"):
        from hal_orchestrator.services.claude_provider import call_claude

        hist = history if is_primary else _strip_claude_blocks(history)
        return await call_claude(
            client, settings, hist, tools, system, model,
            max_retries, max_output_tokens, thinking_level,
        )
    if model.startswith("glm"):
        from hal_orchestrator.services.glm_provider import call_glm

        hist = history if is_primary else _strip_claude_blocks(history)
        return await call_glm(
            client, settings, hist, tools, system, model,
            max_retries, max_output_tokens, thinking_level,
        )
    return await _call_gemini_native(
        client, settings, _strip_claude_blocks(history), tools, system, model,
        max_retries, max_output_tokens, thinking_level,
    )


async def call_gemini(
    client: httpx.AsyncClient,
    settings: HalOrchestratorConfig,
    history: list[dict],
    tools: list[dict] | None = None,
    system: str | None = None,
    model: str | None = None,
    max_retries: int = 3,
    max_output_tokens: int | None = None,
    thinking_level: str | None = None,
) -> dict | None:
    """Call the model with tool defs + history; parsed response or None.

    The MAIN loop (settings.gemini_model) fails over through
    settings.model_fallbacks on failure so a single provider outage doesn't take
    HAL down. The cheap background model (any explicit non-main `model`) is
    called as-is — no failover, so it never escalates onto a premium fallback.
    `max_output_tokens` / `thinking_level` override the defaults for one call.
    """
    global _primary_cooldown_until

    primary = model or settings.gemini_model
    fallbacks = (
        [m for m in _fallback_chain(settings) if m != primary]
        if primary == settings.gemini_model
        else []
    )

    if not fallbacks:
        resp = await _dispatch_model(
            client, settings, history, tools, system, primary,
            max_retries, max_output_tokens, thinking_level, is_primary=True,
        )
        if resp is None:
            # Background failover: an explicitly-passed background model that
            # hard-fails (e.g. GLM out of credits) gets ONE cheap rescue hop to
            # the flash model — never a premium fallback. Without this, an
            # unfunded background provider silently kills the entire proactive
            # layer (heartbeats, critic, growth grading) — which is exactly
            # what happened with glm-5.2 on 2026-07-01.
            rescue = settings.gemini_flash_model
            if rescue and rescue != primary:
                log.warning("model.background_failover", failed=primary, using=rescue)
                resp = await _dispatch_model(
                    client, settings, history, tools, system, rescue,
                    max_retries, max_output_tokens, thinking_level, is_primary=False,
                )
        return resp

    # Skip the primary during its post-failure cooldown (don't re-pay the retry
    # tax every round of a sustained outage); re-probe once the cooldown lapses.
    skip_primary = time.monotonic() < _primary_cooldown_until
    chain = fallbacks if skip_primary else [primary, *fallbacks]
    if skip_primary:
        log.info("model.primary_cooldown", primary=primary, using=chain[0])

    for m in chain:
        resp = await _dispatch_model(
            client, settings, history, tools, system, m,
            max_retries, max_output_tokens, thinking_level, is_primary=(m == primary),
        )
        if resp is not None:
            if m == primary:
                _primary_cooldown_until = 0.0  # healthy again
            else:
                log.warning("model.failover_used", primary=primary, used=m)
            return resp
        if m == primary:
            _primary_cooldown_until = time.monotonic() + _PRIMARY_COOLDOWN_S
            log.error("model.primary_failed", primary=primary, fallbacks=fallbacks)

    log.error("model.all_failed", tried=chain)
    return None


async def _call_gemini_native(
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
    """Native Gemini generateContent call with retry/backoff."""
    url = f"{GEMINI_BASE_URL}/{model}:generateContent?key={settings.gemini_api_key}"

    generation_config: dict = {
        "temperature": settings.gemini_temperature,
        "maxOutputTokens": max_output_tokens or settings.gemini_max_output_tokens,
    }

    # Gemini 3.5+ thinking models — opt in via settings.gemini_thinking_level
    # (LOW/MEDIUM/HIGH), or a per-call `thinking_level` override (e.g. the watch
    # poll forcing MINIMAL). Empty/"NONE" means don't send the field (default
    # off for older models that reject the parameter).
    level = (thinking_level or settings.gemini_thinking_level or "").strip().upper()
    if level and level != "NONE":
        generation_config["thinkingConfig"] = {"thinkingLevel": level}

    payload: dict = {
        "contents": history,
        "generationConfig": generation_config,
    }

    if tools:
        payload["tools"] = tools

    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    backoff_delays = [5, 10, 20]

    for attempt in range(max_retries):
        try:
            resp = await client.post(
                url,
                json=payload,
                timeout=settings.gemini_timeout_seconds,
            )

            if resp.status_code == 200:
                data = resp.json()
                # Surface silent truncation. On thinking models, reasoning
                # tokens are deducted from maxOutputTokens, so a too-low cap
                # can cut the visible answer off mid-sentence (finishReason
                # MAX_TOKENS) after the model "thought" away the budget.
                try:
                    fr = (data.get("candidates") or [{}])[0].get("finishReason")
                    if fr and fr not in ("STOP", "TOOL_CALLS", None):
                        log.warning(
                            "gemini.finish_reason",
                            reason=fr,
                            model=model,
                            max_output_tokens=(
                                max_output_tokens or settings.gemini_max_output_tokens
                            ),
                        )
                except Exception:
                    pass
                return data

            if resp.status_code in RETRYABLE_STATUSES and attempt < max_retries - 1:
                delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                log.warning(
                    "gemini.retryable_error",
                    status=resp.status_code,
                    attempt=attempt + 1,
                    delay=delay,
                )
                await asyncio.sleep(delay)
                continue

            log.error(
                "gemini.api_error",
                status=resp.status_code,
                body=resp.text[:500],
            )
            return None

        except httpx.TimeoutException:
            log.error("gemini.timeout", attempt=attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(backoff_delays[min(attempt, len(backoff_delays) - 1)])
                continue
            return None

        except httpx.HTTPError as exc:
            log.error("gemini.http_error", error=str(exc), attempt=attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(backoff_delays[min(attempt, len(backoff_delays) - 1)])
                continue
            return None

    return None


def get_model_url(settings: HalOrchestratorConfig, model_type: str = "pro") -> str:
    """Get the model name based on type."""
    if model_type == "flash":
        return settings.gemini_flash_model
    return settings.gemini_model
