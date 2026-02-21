"""Shared application state — breaks circular imports between main and routes."""

from __future__ import annotations

import httpx

from ag_common.config import HalOrchestratorConfig

settings = HalOrchestratorConfig()
http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    assert http_client is not None, "HTTP client not initialized"
    return http_client


def get_settings() -> HalOrchestratorConfig:
    return settings
