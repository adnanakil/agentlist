"""Shared application state — breaks circular imports between main and routes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from ag_common.config import HalOrchestratorConfig

settings = HalOrchestratorConfig()
http_client: httpx.AsyncClient | None = None

# Outbox for messages the bridge should send (reminders, async notifications)
# Each item: {"to": "+1...", "text": "message"}
outbox: asyncio.Queue[dict] = asyncio.Queue()

# Cross-daemon proactive-send registry: silo -> when HAL last texted this silo
# UNPROMPTED (heartbeat alert, reminder, cron delivery, helpful brief/ping,
# follow-up). The heartbeat consults it so it never piles a second proactive
# message onto one the user hasn't even seen yet — the 06-27/06-29 bursts of
# ~15 near-identical sends all happened minutes apart. In-memory: a restart
# just forgets the cooldown, which at worst allows one early alert.
proactive_sent: dict[str, datetime] = {}


def mark_proactive_send(silo: str) -> None:
    proactive_sent[silo] = datetime.now(timezone.utc)


def minutes_since_proactive_send(silo: str) -> float | None:
    """Minutes since HAL last proactively texted this silo, or None if never
    (this process lifetime)."""
    at = proactive_sent.get(silo)
    if at is None:
        return None
    return (datetime.now(timezone.utc) - at).total_seconds() / 60.0


def get_http_client() -> httpx.AsyncClient:
    assert http_client is not None, "HTTP client not initialized"
    return http_client


def get_settings() -> HalOrchestratorConfig:
    return settings
