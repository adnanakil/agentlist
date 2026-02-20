"""Web service — FastAPI application with Jinja2 templates."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from ag_common.config import WebConfig
from ag_common.errors import AgentGateError, agentgate_error_handler
from ag_db.session import create_engine_and_session
from web.routes.pages import router as pages_router

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
settings = WebConfig()

TEMPLATES_DIR = Path(__file__).parent / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown lifecycle."""
    log.info("web.startup", database_url=settings.database_url[:30] + "...")
    engine, _ = create_engine_and_session(settings.database_url)
    app.state.config = settings
    yield
    log.info("web.shutdown")
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Dispatch Web",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Session middleware for cookie-based auth
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="agentgate_session",
        max_age=60 * 60 * 24 * 7,  # 7 days
    )

    # Error handlers
    app.add_exception_handler(AgentGateError, agentgate_error_handler)

    # Health check
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "web"}

    # Page routes
    app.include_router(pages_router)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("web.main:app", host="0.0.0.0", port=8004, reload=True)
