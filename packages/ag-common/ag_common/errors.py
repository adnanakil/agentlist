from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AgentGateError(Exception):
    status_code: int = 500
    error_type: str = "internal_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


class AuthenticationError(AgentGateError):
    status_code = 401
    error_type = "authentication_error"


class AuthorizationError(AgentGateError):
    status_code = 403
    error_type = "authorization_error"


class NotFoundError(AgentGateError):
    status_code = 404
    error_type = "not_found"


class ValidationError(AgentGateError):
    status_code = 422
    error_type = "validation_error"


class RateLimitError(AgentGateError):
    status_code = 429
    error_type = "rate_limit_exceeded"


class InsufficientFundsError(AgentGateError):
    status_code = 402
    error_type = "insufficient_funds"


class AgentExecutionError(AgentGateError):
    status_code = 502
    error_type = "agent_execution_error"


class AgentTimeoutError(AgentGateError):
    status_code = 504
    error_type = "agent_timeout"


async def agentgate_error_handler(_request: Request, exc: AgentGateError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "type": exc.error_type,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )
