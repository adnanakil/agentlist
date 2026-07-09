"""Reject oversized requests before FastAPI materializes their bodies."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class _RequestBodyTooLarge(Exception):
    pass


class ContentLengthLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        raw_length = headers.get(b"content-length", b"0")
        try:
            content_length = int(raw_length)
        except ValueError:
            content_length = 0
        if content_length > self.max_bytes:
            response = JSONResponse(
                {"detail": "request body is too large"}, status_code=413
            )
            await response(scope, receive, send)
            return

        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            response = JSONResponse(
                {"detail": "request body is too large"}, status_code=413
            )
            await response(scope, receive, send)
