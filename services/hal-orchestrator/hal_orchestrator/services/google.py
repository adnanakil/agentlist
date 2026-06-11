"""Google OAuth + read-only Calendar/Gmail for HAL (per-silo).

Each user connects their OWN Google account from their 1:1 chat. We hold only
read-only scopes (calendar.readonly, gmail.readonly) and store the resulting
tokens Fernet-encrypted, keyed by silo. All API access goes through raw httpx
(no google client libs) to match the rest of the service.

OAuth-over-text flow:
  1. user: "connect my google"  → google_auth(start)
  2. HAL texts a one-tap consent link (state = HMAC-signed {silo, exp})
  3. user authorizes → Google redirects to /api/google/callback
  4. callback verifies state, exchanges code, stores encrypted tokens for the
     silo, flips profile.google_connected
  5. calendar/gmail tools refresh the access token as needed and call the APIs
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import structlog
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_common.config import HalOrchestratorConfig
from ag_db.models import HalGoogleAccount

log = structlog.get_logger()

# Read-only access only (matches the product decision). openid+email let us show
# WHICH account is connected. Changing this list requires users to reconnect.
SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
CAL_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
GMAIL_LIST_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_MSG_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}"

STATE_TTL_SECONDS = 600  # signed consent links expire after 10 min


# --------------------------------------------------------------------------- #
# Config / readiness
# --------------------------------------------------------------------------- #


def is_configured(settings: HalOrchestratorConfig) -> bool:
    return bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_redirect_uri
        and settings.encryption_key
    )


def _fernet(settings: HalOrchestratorConfig) -> Fernet:
    return Fernet(settings.encryption_key.encode())


def _encrypt(settings: HalOrchestratorConfig, value: str) -> str:
    return _fernet(settings).encrypt(value.encode()).decode()


def _decrypt(settings: HalOrchestratorConfig, token: str) -> str:
    return _fernet(settings).decrypt(token.encode()).decode()


# --------------------------------------------------------------------------- #
# Signed state (binds a consent link to one silo, tamper-proof, short-lived)
# --------------------------------------------------------------------------- #


def sign_state(settings: HalOrchestratorConfig, silo: str) -> str:
    payload = {"silo": silo, "exp": int(time.time()) + STATE_TTL_SECONDS}
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(
        settings.encryption_key.encode(), raw.encode(), hashlib.sha256
    ).hexdigest()[:32]
    return f"{raw}.{sig}"


def verify_state(settings: HalOrchestratorConfig, state: str) -> str | None:
    """Return the silo if the state is valid and unexpired, else None."""
    try:
        raw, sig = state.rsplit(".", 1)
    except ValueError:
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


def build_auth_url(settings: HalOrchestratorConfig, silo: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",  # request a refresh token
        "prompt": "consent",  # force refresh-token issuance on reconnect
        "include_granted_scopes": "true",
        "state": sign_state(settings, silo),
    }
    return f"{AUTH_URL}?{urlencode(params)}"


# --------------------------------------------------------------------------- #
# Token exchange / refresh
# --------------------------------------------------------------------------- #


async def exchange_code(
    client: httpx.AsyncClient, settings: HalOrchestratorConfig, code: str
) -> dict | None:
    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        r = await client.post(TOKEN_URL, data=data, timeout=30)
        if r.status_code != 200:
            log.error("google.exchange_failed", status=r.status_code, body=r.text[:300])
            return None
        return r.json()
    except Exception:
        log.exception("google.exchange_error")
        return None


async def _fetch_email(
    client: httpx.AsyncClient, access_token: str
) -> str | None:
    try:
        r = await client.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if r.status_code == 200:
            return r.json().get("email")
    except Exception:
        log.exception("google.userinfo_error")
    return None


async def save_tokens(
    session: AsyncSession,
    settings: HalOrchestratorConfig,
    client: httpx.AsyncClient,
    silo: str,
    token_resp: dict,
) -> str | None:
    """Persist tokens from an exchange/refresh response. Returns google_email."""
    access = token_resp.get("access_token")
    if not access:
        return None
    expires_in = int(token_resp.get("expires_in", 3600))
    expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    email = await _fetch_email(client, access)

    stmt = select(HalGoogleAccount).where(HalGoogleAccount.phone == silo)
    acct = (await session.execute(stmt)).scalar_one_or_none()
    if acct is None:
        acct = HalGoogleAccount(phone=silo)
        session.add(acct)

    acct.access_token_enc = _encrypt(settings, access)
    # Google only returns refresh_token on the first consent; keep the old one
    # on a plain refresh response.
    refresh = token_resp.get("refresh_token")
    if refresh:
        acct.refresh_token_enc = _encrypt(settings, refresh)
    acct.token_expiry = expiry
    acct.scopes = token_resp.get("scope", " ".join(SCOPES))
    if email:
        acct.google_email = email
    await session.flush()
    return email or acct.google_email


async def get_account(
    session: AsyncSession, silo: str
) -> HalGoogleAccount | None:
    stmt = select(HalGoogleAccount).where(HalGoogleAccount.phone == silo)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_valid_access_token(
    session: AsyncSession,
    settings: HalOrchestratorConfig,
    client: httpx.AsyncClient,
    silo: str,
) -> str | None:
    """Return a usable access token for the silo, refreshing if expired."""
    acct = await get_account(session, silo)
    if acct is None or not acct.access_token_enc:
        return None

    # Still valid (60s margin)?
    if acct.token_expiry and acct.token_expiry > datetime.now(timezone.utc) + timedelta(seconds=60):
        try:
            return _decrypt(settings, acct.access_token_enc)
        except InvalidToken:
            log.error("google.decrypt_failed", silo=silo)
            return None

    # Refresh.
    if not acct.refresh_token_enc:
        return None
    try:
        refresh = _decrypt(settings, acct.refresh_token_enc)
    except InvalidToken:
        log.error("google.decrypt_refresh_failed", silo=silo)
        return None

    data = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    }
    try:
        r = await client.post(TOKEN_URL, data=data, timeout=30)
    except Exception:
        log.exception("google.refresh_error", silo=silo)
        return None
    if r.status_code != 200:
        log.error("google.refresh_failed", silo=silo, status=r.status_code, body=r.text[:200])
        return None
    await save_tokens(session, settings, client, silo, r.json())
    await session.flush()
    return r.json().get("access_token")


async def disconnect(
    session: AsyncSession,
    settings: HalOrchestratorConfig,
    client: httpx.AsyncClient,
    silo: str,
) -> bool:
    acct = await get_account(session, silo)
    if acct is None:
        return False
    # Best-effort revoke at Google, then delete locally.
    token_enc = acct.refresh_token_enc or acct.access_token_enc
    if token_enc:
        try:
            tok = _decrypt(settings, token_enc)
            await client.post(REVOKE_URL, data={"token": tok}, timeout=15)
        except Exception:
            log.warning("google.revoke_failed", silo=silo)
    await session.delete(acct)
    await session.flush()
    return True


# --------------------------------------------------------------------------- #
# Calendar (read-only)
# --------------------------------------------------------------------------- #


async def list_events(
    client: httpx.AsyncClient,
    access_token: str,
    time_min: str,
    time_max: str,
    max_results: int = 10,
    query: str | None = None,
) -> list[dict] | None:
    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": str(max_results),
    }
    if query:
        params["q"] = query
    try:
        r = await client.get(
            CAL_EVENTS_URL,
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
    except Exception:
        log.exception("google.calendar_error")
        return None
    if r.status_code != 200:
        log.error("google.calendar_http", status=r.status_code, body=r.text[:200])
        return None
    out = []
    for ev in r.json().get("items", []):
        start = ev.get("start", {})
        out.append(
            {
                "summary": ev.get("summary", "(no title)"),
                "start": start.get("dateTime") or start.get("date"),
                "end": (ev.get("end") or {}).get("dateTime")
                or (ev.get("end") or {}).get("date"),
                "location": ev.get("location"),
                "all_day": "date" in start,
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Gmail (read-only)
# --------------------------------------------------------------------------- #


def _header(payload: dict, name: str) -> str:
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _extract_body(payload: dict) -> str:
    """Best-effort plain-text body from a Gmail message payload."""
    def walk(part: dict) -> str | None:
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if mime == "text/plain" and data:
            return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", "replace"
            )
        for sub in part.get("parts", []) or []:
            found = walk(sub)
            if found:
                return found
        return None

    return (walk(payload) or "").strip()


async def list_messages(
    client: httpx.AsyncClient,
    access_token: str,
    query: str = "is:unread",
    max_results: int = 10,
) -> list[dict] | None:
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        r = await client.get(
            GMAIL_LIST_URL,
            params={"q": query, "maxResults": str(max_results)},
            headers=headers,
            timeout=30,
        )
    except Exception:
        log.exception("google.gmail_list_error")
        return None
    if r.status_code != 200:
        log.error("google.gmail_list_http", status=r.status_code, body=r.text[:200])
        return None
    ids = [m["id"] for m in r.json().get("messages", [])]
    out = []
    for mid in ids:
        try:
            mr = await client.get(
                GMAIL_MSG_URL.format(id=mid),
                params={
                    "format": "metadata",
                    "metadataHeaders": ["From", "Subject", "Date"],
                },
                headers=headers,
                timeout=20,
            )
            if mr.status_code != 200:
                continue
            msg = mr.json()
            payload = msg.get("payload", {})
            out.append(
                {
                    "id": mid,
                    "from": _header(payload, "From"),
                    "subject": _header(payload, "Subject"),
                    "date": _header(payload, "Date"),
                    "snippet": msg.get("snippet", ""),
                }
            )
        except Exception:
            log.exception("google.gmail_meta_error", id=mid)
    return out


async def get_message(
    client: httpx.AsyncClient, access_token: str, message_id: str
) -> dict | None:
    try:
        r = await client.get(
            GMAIL_MSG_URL.format(id=message_id),
            params={"format": "full"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
    except Exception:
        log.exception("google.gmail_get_error")
        return None
    if r.status_code != 200:
        log.error("google.gmail_get_http", status=r.status_code, body=r.text[:200])
        return None
    msg = r.json()
    payload = msg.get("payload", {})
    return {
        "id": message_id,
        "from": _header(payload, "From"),
        "to": _header(payload, "To"),
        "subject": _header(payload, "Subject"),
        "date": _header(payload, "Date"),
        "body": _extract_body(payload)[:4000],
    }
