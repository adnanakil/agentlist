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
from hal_orchestrator.routes.admin import build_admin_router
from hal_orchestrator.routes.google import build_google_router
from hal_orchestrator.routes.landing import build_landing_router
from hal_orchestrator.routes.message import build_message_router
from hal_orchestrator.services.baby_watch import baby_watch_loop
from hal_orchestrator.services.cron import run_cron_checker
from hal_orchestrator.services.curator import curator_loop
from hal_orchestrator.services.profile_enricher import profile_enricher_loop
from hal_orchestrator.services.growth import growth_loop
from hal_orchestrator.services.heartbeat import heartbeat_loop
from hal_orchestrator.services.helpful import helpful_loop
from hal_orchestrator.services.reminders import run_reminder_checker
from hal_orchestrator.services.skill_synthesizer import skill_synthesizer_loop
from hal_orchestrator.services.summarizer import summarizer_loop
from hal_orchestrator.services.watch import run_watch_checker

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

    # Start skills curator background task (no-op until interval+idle gates pass)
    curator_task = asyncio.create_task(
        curator_loop(settings, state.http_client)
    )

    # Start conversation summarizer background task (~20 min cadence)
    summarizer_task = asyncio.create_task(
        summarizer_loop(settings, state.http_client)
    )

    # Start profile enricher background task (~30 min cadence): distills durable
    # preferences/needs (1:1) or interests/dynamics/goals (group) into the
    # silo's structured profile, so the agent knows each user/group better over time.
    enricher_task = asyncio.create_task(
        profile_enricher_loop(settings, state.http_client)
    )

    # Agentic cron (scheduled full agent turns) + auto-skill synthesizer.
    cron_task = asyncio.create_task(run_cron_checker(settings, state.http_client))
    synth_task = asyncio.create_task(
        skill_synthesizer_loop(settings, state.http_client)
    )

    # Nightly growth loop: grade every turn in-silo, aggregate de-identified
    # verdicts, self-author playbook notes + skills, maintain the feature
    # backlog, verify past improvements (GROWTH.md).
    reflection_task = asyncio.create_task(
        growth_loop(settings, state.http_client)
    )

    # Baby nap-cap watcher: unprompted nudge when a logged nap runs long.
    baby_watch_task = asyncio.create_task(
        baby_watch_loop(settings, state.http_client)
    )

    # Heartbeat: per-silo anticipation checks (upcoming plans vs traffic /
    # weather / expected emails). Silent by default; texts only when useful.
    heartbeat_task = asyncio.create_task(
        heartbeat_loop(settings, state.http_client)
    )

    # Helpful mode: OPT-IN proactive concierge — a daily situation/location-aware
    # brief (weather, local events, news, agenda) + a few capped same-day pings.
    helpful_task = asyncio.create_task(
        helpful_loop(settings, state.http_client)
    )

    # Watch checker: re-polls notify-when conditions on a cheap model and fires
    # once when true. Silent until then (WATCH_FEATURE_SPEC.md).
    watch_task = asyncio.create_task(
        run_watch_checker(settings, state.http_client)
    )

    yield

    log.info("hal_orchestrator.shutdown")
    for task in (
        reminder_task,
        curator_task,
        summarizer_task,
        enricher_task,
        cron_task,
        synth_task,
        reflection_task,
        baby_watch_task,
        heartbeat_task,
        helpful_task,
        watch_task,
    ):
        task.cancel()
        try:
            await task
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

    # Google OAuth callback (public landing page after consent)
    application.include_router(build_google_router())

    # Admin dashboard (token-protected, read-only)
    application.include_router(build_admin_router())

    # Public landing page (tryhal.com)
    application.include_router(build_landing_router())

    return application


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #

app = create_app()

if __name__ == "__main__":
    uvicorn.run("hal_orchestrator.main:app", host="0.0.0.0", port=8005, reload=True)
