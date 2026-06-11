"""Shared crypto helpers — Fernet encryption + HMAC signed state.

Lifted so the Google and Resy integrations (and future ones) share one
implementation. Uses settings.encryption_key (a Fernet key, urlsafe-base64 of
32 bytes). Signed state binds a web-flow link to one silo, tamper-proof and
short-lived.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from cryptography.fernet import Fernet

STATE_TTL_SECONDS = 600  # signed links expire after 10 min


def fernet(settings) -> Fernet:
    return Fernet(settings.encryption_key.encode())


def encrypt(settings, value: str) -> str:
    return fernet(settings).encrypt(value.encode()).decode()


def decrypt(settings, token: str) -> str:
    return fernet(settings).decrypt(token.encode()).decode()


def sign_state(settings, silo: str, ttl: int = STATE_TTL_SECONDS) -> str:
    payload = {"silo": silo, "exp": int(time.time()) + ttl}
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(
        settings.encryption_key.encode(), raw.encode(), hashlib.sha256
    ).hexdigest()[:32]
    return f"{raw}.{sig}"


def verify_state(settings, state: str) -> str | None:
    """Return the silo if the signed state is valid + unexpired, else None."""
    try:
        raw, sig = state.rsplit(".", 1)
    except (ValueError, AttributeError):
        return None
    expected = hmac.new(
        settings.encryption_key.encode(), raw.encode(), hashlib.sha256
    ).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    silo = payload.get("silo")
    return silo if isinstance(silo, str) and silo else None


def jwt_exp(token: str) -> int | None:
    """Read the `exp` claim from a JWT without verifying (we trust our own
    stored token; we only need its expiry). Returns epoch seconds or None."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()))
        exp = payload.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None
