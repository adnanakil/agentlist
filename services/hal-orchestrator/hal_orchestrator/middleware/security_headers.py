"""Security response headers on every HTTP response.

Added ahead of the CASA AL1 assessment: a DAST baseline (ZAP) flags their
absence. The CSP is deliberately tight — the only HTML this service serves
(landing, legal, connect interstitials) uses inline <style> blocks and
data:/self images, and there is no first-party JavaScript anywhere.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

_HEADERS: list[tuple[bytes, bytes]] = [
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (
        b"content-security-policy",
        b"default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
        b"form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    ),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {name.lower() for name, _ in headers}
                headers.extend(
                    (name, value) for name, value in _HEADERS if name not in present
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
