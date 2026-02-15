"""Request-ID middleware — attaches a unique X-Request-ID to every request and response."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Injects a UUID4 X-Request-ID header into every request/response cycle.

    If the incoming request already carries an X-Request-ID header, it is
    forwarded as-is; otherwise a new one is generated.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())

        # Make the ID available to downstream handlers via request.state
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
