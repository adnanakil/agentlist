"""Shared application state — breaks circular imports between main and routes."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ag_common.config import HalOrchestratorConfig
from hal_orchestrator.services.delivery import outbox as outbox

settings = HalOrchestratorConfig()
http_client: httpx.AsyncClient | None = None

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


# In-flight registry: silo -> when a proactive turn STARTED but hasn't delivered
# yet. The sent-registry above only marks at DELIVERY, so two proactive turns
# firing seconds apart (the 07-07 /morning-brief cron + heartbeat, 16s apart)
# each pass their cooldown check before the other's mark lands. This closes
# that race: an explicit sender (cron/reminder/followup) marks in-flight the
# moment it starts, and the opportunistic heartbeat defers to it. Bounded age
# so a crashed turn can't block a silo forever.
proactive_inflight: dict[str, datetime] = {}


def begin_proactive(silo: str) -> None:
    proactive_inflight[silo] = datetime.now(timezone.utc)


def end_proactive(silo: str) -> None:
    proactive_inflight.pop(silo, None)


def is_proactive_inflight(silo: str, max_age_seconds: float = 240.0) -> bool:
    at = proactive_inflight.get(silo)
    if at is None:
        return False
    return (datetime.now(timezone.utc) - at).total_seconds() < max_age_seconds


def get_http_client() -> httpx.AsyncClient:
    assert http_client is not None, "HTTP client not initialized"
    return http_client


def get_settings() -> HalOrchestratorConfig:
    return settings
