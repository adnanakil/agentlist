"""Gateway application factory."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from ag_common.errors import AgentGateError, agentgate_error_handler
from ag_db.session import create_engine_and_session
from gateway.config import settings
from gateway.deps import close_http_client, close_redis
from gateway.middleware.auth import RequestIDMiddleware
from gateway.routes import billing, discover, health, invoke, mcp


def _configure_structlog() -> None:
    """Set up structlog with JSON rendering in production, console in dev."""
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.environment == "production":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup and shutdown resources."""
    logger = structlog.get_logger()

    # --- Startup ---
    logger.info("gateway_starting", environment=settings.environment)

    engine, _session_factory = create_engine_and_session(
        settings.database_url,
        echo=(settings.environment == "development"),
    )

    logger.info("gateway_started")

    yield

    # --- Shutdown ---
    logger.info("gateway_shutting_down")

    await close_http_client()
    await close_redis()
    await engine.dispose()

    logger.info("gateway_stopped")


def create_app() -> FastAPI:
    """Build and return the fully-configured FastAPI application."""
    _configure_structlog()

    app = FastAPI(
        title="AgentGate API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # --- Exception handlers ---
    app.add_exception_handler(AgentGateError, agentgate_error_handler)  # type: ignore[arg-type]

    # --- Middleware (outermost first) ---
    @app.middleware("http")
    async def legacy_hal_domain_redirect(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # HAL's retired tryhal.xyz domain parks on this service (Railway caps
        # custom domains per service, and hal-orchestrator's slots hold
        # texthal.com); redirect it home so old links keep working.
        host = request.headers.get("host", "").split(":")[0].lower()
        if host == "tryhal.xyz" or host.endswith(".tryhal.xyz"):
            return RedirectResponse(
                url=f"https://www.texthal.com{request.url.path}", status_code=301
            )
        return await call_next(request)

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Route routers ---
    app.include_router(health.router)
    app.include_router(discover.router)
    app.include_router(invoke.router)
    app.include_router(mcp.router)
    app.include_router(billing.router)

    return app


app = create_app()
