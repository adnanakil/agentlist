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
from sqlalchemy import text

import hal_orchestrator.state as state
from ag_db.session import create_engine_and_session
from hal_orchestrator.middleware.request_size import ContentLengthLimitMiddleware
from hal_orchestrator.middleware.security_headers import SecurityHeadersMiddleware
from hal_orchestrator.routes.admin import build_admin_router
from hal_orchestrator.routes.card import build_card_router
from hal_orchestrator.routes.google import build_google_router
from hal_orchestrator.routes.landing import build_landing_router
from hal_orchestrator.routes.legal import build_legal_router
from hal_orchestrator.routes.message import build_message_router
from hal_orchestrator.routes.stripe import build_stripe_router
from hal_orchestrator.services.baby_watch import baby_watch_loop
from hal_orchestrator.services.cron import run_cron_checker
from hal_orchestrator.services.curator import curator_loop
from hal_orchestrator.services.followup import followup_loop
from hal_orchestrator.services.growth import growth_loop
from hal_orchestrator.services.heartbeat import heartbeat_loop
from hal_orchestrator.services.helpful import helpful_loop
from hal_orchestrator.services.profile_enricher import profile_enricher_loop
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


def _validate_production_config(settings) -> None:
    """Fail closed on an insecure production boot.

    In production a missing bridge secret leaves the message API open, and a
    missing/invalid Fernet key means OAuth tokens can't be encrypted at rest.
    Refuse to start rather than run silently insecure. Outside production these
    are warnings so local dev keeps working.
    """
    problems: list[str] = []
    if not settings.hal_bridge_secret:
        problems.append("HAL_BRIDGE_SECRET is not set (message API would be unauthenticated)")
    if settings.encryption_key:
        try:
            from cryptography.fernet import Fernet

            Fernet(settings.encryption_key.encode())
        except Exception:
            problems.append("ENCRYPTION_KEY is not a valid Fernet key")
    else:
        problems.append("ENCRYPTION_KEY is not set (OAuth tokens can't be encrypted)")
    if not getattr(settings, "card_signing_key", ""):
        problems.append("CARD_SIGNING_KEY is not set (card links share the bridge secret)")
    if getattr(settings, "hal_process_role", "all") not in ("api", "worker", "all"):
        problems.append("HAL_PROCESS_ROLE must be api, worker, or all")

    is_prod = (settings.environment or "").lower() in ("production", "prod")
    if problems and is_prod:
        raise RuntimeError(
            "Refusing to start in production with insecure config: "
            + "; ".join(problems)
        )
    for p in problems:
        log.warning("hal_orchestrator.config_warning", issue=p)


def _worker_coroutines(settings, http_client) -> tuple:
    return (
        run_reminder_checker(settings, http_client),
        curator_loop(settings, http_client),
        summarizer_loop(settings, http_client),
        profile_enricher_loop(settings, http_client),
        run_cron_checker(settings, http_client),
        skill_synthesizer_loop(settings, http_client),
        growth_loop(settings, http_client),
        baby_watch_loop(settings, http_client),
        heartbeat_loop(settings, http_client),
        helpful_loop(settings, http_client),
        run_watch_checker(settings, http_client),
        followup_loop(settings, http_client),
    )


async def _run_worker_set(settings, http_client, leader_connection=None) -> None:
    """Run one daemon set until cancellation, connection loss, or loop death."""
    tasks = [asyncio.create_task(loop) for loop in _worker_coroutines(settings, http_client)]
    log.info("hal_orchestrator.worker_leader", tasks=len(tasks))
    try:
        while True:
            done, _ = await asyncio.wait(
                tasks,
                timeout=10,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if done:
                for task in done:
                    if task.cancelled():
                        continue
                    error = task.exception()
                    if error is not None:
                        log.error(
                            "hal_orchestrator.worker_loop_failed",
                            error=str(error),
                        )
                    else:
                        log.error("hal_orchestrator.worker_loop_stopped")
                return
            if leader_connection is not None:
                try:
                    await leader_connection.execute(text("SELECT 1"))
                    await leader_connection.commit()
                except Exception:
                    log.exception("hal_orchestrator.worker_leadership_lost")
                    return
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _worker_supervisor(engine, settings, http_client) -> None:
    """Continuously elect and supervise the single proactive worker leader."""
    while True:
        try:
            if not settings.worker_leader_lock_enabled:
                await _run_worker_set(settings, http_client)
            else:
                async with engine.connect() as connection:
                    acquired = await connection.scalar(
                        text(
                            "SELECT pg_try_advisory_lock("
                            "hashtext('hal-background-worker-v1'))"
                        )
                    )
                    await connection.commit()
                    if acquired:
                        await _run_worker_set(settings, http_client, connection)
                    else:
                        log.info("hal_orchestrator.worker_standby")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("hal_orchestrator.worker_supervisor_failed")
        await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = state.settings

    _validate_production_config(settings)

    log.info("hal_orchestrator.startup", database_url=settings.database_url[:30] + "...")
    engine, _ = create_engine_and_session(settings.database_url)
    app.state.config = settings

    state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.gemini_timeout_seconds + 10)
    )

    tasks: list[asyncio.Task] = []
    run_workers = settings.hal_process_role in ("worker", "all")
    if run_workers:
        tasks.append(
            asyncio.create_task(
                _worker_supervisor(engine, settings, state.http_client)
            )
        )

    yield

    log.info("hal_orchestrator.shutdown")
    for task in tasks:
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
    application.add_middleware(
        ContentLengthLimitMiddleware, max_bytes=state.settings.max_request_bytes
    )
    application.add_middleware(SecurityHeadersMiddleware)

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

    # Public landing page (tryhal.xyz)
    application.include_router(build_landing_router())

    # Stripe payment webhook (pay -> auto-unlock the message cap)
    application.include_router(build_stripe_router())

    # Privacy Policy + Terms (required + linked from the Google consent screen)
    application.include_router(build_legal_router())

    # Public signed baby-status card image (iMessage inline preview).
    application.include_router(build_card_router())

    return application


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #

app = create_app()

if __name__ == "__main__":
    uvicorn.run("hal_orchestrator.main:app", host="0.0.0.0", port=8005, reload=True)
