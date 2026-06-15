"""Friction logging — demand/struggle signals for the nightly reflection.

Best-effort: every call site wraps this so it can never break tool execution or
a reply. Rows persist when the turn's session commits.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalFrictionEvent

log = structlog.get_logger()

KIND_STUB = "stub_tool"     # a not-yet-built tool was requested → unmet demand
KIND_STUCK = "stuck"        # turn hit the iteration cap → capability gap
KIND_TOOL_ERROR = "tool_error"
KIND_REFUSAL = "capability_refusal"  # HAL told the user it can't do something
KIND_MODEL_FAILURE = "model_failure"  # Gemini failure / circuit breaker
KIND_CRITIC_CATCH = "critic_catch"  # self-critique caught a flawed plan/rec


def log_friction(session: AsyncSession, phone: str, kind: str, detail: str = "") -> None:
    """Queue a friction event on the session (committed with the turn)."""
    session.add(
        HalFrictionEvent(
            phone=(phone or "")[:255], kind=kind, detail=(detail or "")[:500]
        )
    )
