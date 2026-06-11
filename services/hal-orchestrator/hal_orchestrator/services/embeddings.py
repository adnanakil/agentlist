"""Gemini text embeddings (gemini-embedding-001, 768-dim) for semantic memory recall.

pgvector isn't available on the Railway Postgres, so embeddings are stored as a
JSONB float array and cosine similarity is computed in app code. Per-user memory
counts are small (tens–low hundreds), so brute-force cosine is instant.
"""

from __future__ import annotations

import math

import httpx
import structlog

from ag_common.config import HalOrchestratorConfig

log = structlog.get_logger()

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


async def embed_text(
    client: httpx.AsyncClient, settings: HalOrchestratorConfig, text: str
) -> list[float] | None:
    """Return a 768-dim embedding for text, or None on failure."""
    if not text or not text.strip():
        return None
    url = f"{BASE_URL}/{EMBED_MODEL}:embedContent?key={settings.gemini_api_key}"
    payload = {
        "content": {"parts": [{"text": text[:2000]}]},
        "outputDimensionality": EMBED_DIM,
    }
    try:
        resp = await client.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("embedding", {}).get("values")
        log.warning("embed.http_error", status=resp.status_code, body=resp.text[:200])
    except Exception:
        log.exception("embed.error")
    return None


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    """Cosine similarity; returns -1.0 on invalid input."""
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return -1.0
    return dot / (na * nb)
