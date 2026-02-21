"""HAL Orchestrator — FastAPI application factory.

Cloud-based brain for HAL: receives messages from the iMessage bridge,
processes them through Gemini with tool use, and returns responses.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
import structlog
import uvicorn
from fastapi import FastAPI

from ag_db.session import create_engine_and_session

import hal_orchestrator.state as state
from hal_orchestrator.routes.message import build_message_router
from hal_orchestrator.services.reminders import run_reminder_checker

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()


# --------------------------------------------------------------------------- #
# Lifespan
# --------------------------------------------------------------------------- #


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = state.settings

    log.info("hal_orchestrator.startup", database_url=settings.database_url[:30] + "...")
    engine, _ = create_engine_and_session(settings.database_url)
    app.state.config = settings

    state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.gemini_timeout_seconds + 10)
    )

    # Start reminder background task
    reminder_task = asyncio.create_task(
        run_reminder_checker(settings, state.http_client)
    )

    yield

    log.info("hal_orchestrator.shutdown")
    reminder_task.cancel()
    try:
        await reminder_task
    except asyncio.CancelledError:
        pass
    if state.http_client:
        await state.http_client.aclose()
    await engine.dispose()


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #


def create_app() -> FastAPI:
    application = FastAPI(
        title="HAL Orchestrator",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Health check
    @application.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "hal-orchestrator"}

    # Message processing
    application.include_router(build_message_router())

    return application


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #

app = create_app()

if __name__ == "__main__":
    uvicorn.run("hal_orchestrator.main:app", host="0.0.0.0", port=8005, reload=True)
