"""SSRF guard for user-directed fetches (web_fetch, browser).

The model chooses the URL from user text, so a stranger can steer HAL at
`http://169.254.169.254/…` (cloud metadata), `http://localhost:8005/admin`,
or a Railway private host like `http://postgres.railway.internal:5432` and get
the response echoed back into the chat. This module refuses any URL that is not
plain http(s) to a PUBLIC host.

Defense: reject non-http(s) schemes and credentialed URLs, reject hostnames that
are obviously internal (localhost, *.internal, *.local, raw private IPs), then
resolve the hostname and reject if ANY resolved address is loopback / private /
link-local / reserved / multicast. Resolution + a fresh connection is a small
TOCTOU (DNS-rebinding) window, but resolving-and-checking blocks every realistic
natural-language attack and raises the bar far above "fetch whatever the model
typed". A single-tenant self-host can opt out with allow_private_network_fetch.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

# Hostnames that never belong to a legitimate public fetch.
_BLOCKED_SUFFIXES = (".internal", ".local", ".localhost", ".railway.internal")
_BLOCKED_EXACT = {"localhost", "metadata", "metadata.google.internal"}


def _ip_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


async def check_url(url: str, *, allow_private: bool = False) -> str | None:
    """Return None if `url` is safe to fetch, else a short refusal reason.

    `allow_private=True` disables the guard entirely (trusted self-host).
    """
    if allow_private:
        return None

    try:
        parts = urlsplit(url)
    except ValueError:
        return "malformed URL"

    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        return f"scheme '{scheme or '(none)'}' not allowed — only http(s)"
    if parts.username or parts.password:
        return "credentials in URL not allowed"

    host = (parts.hostname or "").strip().rstrip(".").lower()
    if not host:
        return "no host in URL"

    if host in _BLOCKED_EXACT or host.endswith(_BLOCKED_SUFFIXES):
        return "host resolves to an internal address"

    # A literal IP in the URL — check it directly.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return None if _ip_is_public(host) else "host is a private/reserved IP"

    # Resolve the hostname; every resolved address must be public.
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, parts.port or None, 0, socket.SOCK_STREAM
        )
    except socket.gaierror:
        return f"could not resolve host '{host}'"
    except Exception:
        return "host resolution failed"

    addrs = {info[4][0] for info in infos}
    if not addrs:
        return f"could not resolve host '{host}'"
    for ip in addrs:
        if not _ip_is_public(ip):
            return "host resolves to a private/reserved address"
    return None
