"""Gemini API client — async HTTP calls with retry logic."""

from __future__ import annotations

import asyncio

import httpx
import structlog

from ag_common.config import HalOrchestratorConfig

log = structlog.get_logger()

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Retryable HTTP status codes
RETRYABLE_STATUSES = {429, 500, 502, 503}


async def call_gemini(
    client: httpx.AsyncClient,
    settings: HalOrchestratorConfig,
    history: list[dict],
    tools: list[dict] | None = None,
    system: str | None = None,
    model: str | None = None,
    max_retries: int = 3,
) -> dict | None:
    """Call Gemini API with tool definitions and conversation history.

    Returns the parsed JSON response, or None on failure.
    """
    model = model or settings.gemini_model
    url = f"{GEMINI_BASE_URL}/{model}:generateContent?key={settings.gemini_api_key}"

    payload: dict = {
        "contents": history,
        "generationConfig": {
            "temperature": settings.gemini_temperature,
            "maxOutputTokens": settings.gemini_max_output_tokens,
        },
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
                return resp.json()

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
