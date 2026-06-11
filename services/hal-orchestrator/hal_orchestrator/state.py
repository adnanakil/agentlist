"""Shared application state — breaks circular imports between main and routes."""

from __future__ import annotations

import asyncio

import httpx

from ag_common.config import HalOrchestratorConfig

settings = HalOrchestratorConfig()
http_client: httpx.AsyncClient | None = None

# Outbox for messages the bridge should send (reminders, async notifications)
# Each item: {"to": "+1...", "text": "message"}
outbox: asyncio.Queue[dict] = asyncio.Queue()


def get_http_client() -> httpx.AsyncClient:
    assert http_client is not None, "HTTP client not initialized"
    return http_client


def get_settings() -> HalOrchestratorConfig:
    return settings
