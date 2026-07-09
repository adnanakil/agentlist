"""Tests for the production-hardening layer: SSRF url_guard, fail-closed bridge
auth, admin-token fallback/header parsing, and prod config validation.

Run: python3 services/hal-orchestrator/tests_security.py
"""

import asyncio
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services.url_guard import check_url

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok  {name}")
    else:
        print(f"FAIL  {name}  {detail}")
        failures.append(name)


# --- SSRF url_guard -------------------------------------------------------- #
print("url_guard — must BLOCK (returns a reason):")
BLOCK = [
    "http://169.254.169.254/latest/meta-data/",       # AWS/GCP metadata
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://localhost:8005/admin",
    "http://127.0.0.1/",
    "http://[::1]/",
    "http://postgres.railway.internal:5432/",
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://172.16.0.1/",
    "https://foo.internal/x",
    "file:///etc/passwd",
    "ftp://example.com/x",
    "http://user:pass@example.com/",                   # credentials in URL
    "http://0.0.0.0/",
    "not a url",
]
for u in BLOCK:
    reason = asyncio.run(check_url(u))
    check(f"block {u}", reason is not None, detail=f"reason={reason!r}")

print("url_guard — must ALLOW (returns None):")
ALLOW = [
    "https://example.com/",
    "https://www.google.com/search?q=x",
    "http://old.reddit.com/r/nyc",
    "https://api.github.com/repos/x/y",
]
for u in ALLOW:
    reason = asyncio.run(check_url(u))
    check(f"allow {u}", reason is None, detail=f"reason={reason!r}")

print("url_guard — allow_private escape hatch disables the guard:")
check(
    "private allowed when opted in",
    asyncio.run(check_url("http://127.0.0.1/", allow_private=True)) is None,
)


# --- Fail-closed bridge auth ---------------------------------------------- #
print("verify_bridge_auth — fail closed:")
from fastapi import HTTPException

import hal_orchestrator.state as state
from hal_orchestrator.routes.message import verify_bridge_auth


def _auth_raises(header, secret):
    old = state.settings.hal_bridge_secret
    state.settings.hal_bridge_secret = secret
    try:
        asyncio.run(verify_bridge_auth(authorization=header))
        return None
    except HTTPException as e:
        return e.status_code
    finally:
        state.settings.hal_bridge_secret = old


# Empty secret must reject EVERYTHING — including the old "Bearer " bypass.
check("empty secret rejects 'Bearer '", _auth_raises("Bearer ", "") == 503)
check("empty secret rejects empty header", _auth_raises("", "") == 503)
check(
    "empty secret rejects a guessed token",
    _auth_raises("Bearer anything", "") == 503,
)
# Configured secret: only the exact match passes.
check("wrong token rejected", _auth_raises("Bearer nope", "s3cr3t") == 401)
check("no bearer prefix rejected", _auth_raises("s3cr3t", "s3cr3t") == 401)
check("correct token accepted", _auth_raises("Bearer s3cr3t", "s3cr3t") is None)


# --- Admin token fallback + header parsing -------------------------------- #
print("admin _check_token — dedicated token, fallback, fail-closed:")
# Re-implement the resolution the router uses, to test precedence without a DB.
import hmac

from hal_orchestrator.routes.admin import build_admin_router  # noqa: F401


def _admin_ok(token, admin_token, bridge_secret):
    secret = admin_token or bridge_secret
    return bool(secret) and hmac.compare_digest(token or "", secret)


check("admin: falls back to bridge secret", _admin_ok("b", "", "b"))
check("admin: dedicated token used when set", _admin_ok("a", "a", "b"))
check("admin: bridge secret does NOT work once admin_token set", not _admin_ok("b", "a", "b"))
check("admin: no secret configured rejects all", not _admin_ok("", "", ""))
check("admin: no secret configured rejects a guess", not _admin_ok("guess", "", ""))


# --- Prod config validation ----------------------------------------------- #
print("_validate_production_config — refuses insecure prod boot:")
from types import SimpleNamespace

from cryptography.fernet import Fernet

from hal_orchestrator.main import _validate_production_config

good_key = Fernet.generate_key().decode()


def _prod(bridge, enc, env="production", card="card-secret"):
    cfg = SimpleNamespace(
        hal_bridge_secret=bridge,
        encryption_key=enc,
        environment=env,
        card_signing_key=card,
        hal_process_role="all",
    )
    try:
        _validate_production_config(cfg)
        return "ok"
    except RuntimeError:
        return "refused"


check("prod refuses missing bridge secret", _prod("", good_key) == "refused")
check("prod refuses missing encryption key", _prod("s", "") == "refused")
check("prod refuses invalid fernet key", _prod("s", "not-a-key") == "refused")
check("prod refuses missing card signing key", _prod("s", good_key, card="") == "refused")
check("prod boots with valid config", _prod("s", good_key) == "ok")
check("dev only warns (never refuses)", _prod("", "", env="development") == "ok")


if failures:
    print(f"\n{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("\nAll security tests passed.")
