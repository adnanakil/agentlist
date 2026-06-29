"""Billing service — FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI

from ag_common.config import BillingConfig
from ag_common.errors import AgentGateError, agentgate_error_handler
from ag_db.session import create_engine_and_session

from billing.routes.accounts import router as accounts_router
from billing.routes.stripe_webhook import router as stripe_router
from billing.routes.transactions import router as transactions_router

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
settings = BillingConfig()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown lifecycle."""
    log.info("billing.startup", database_url=settings.database_url[:30] + "...")
    engine, _ = create_engine_and_session(settings.database_url)
    app.state.config = settings
    yield
    log.info("billing.shutdown")
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentGate Billing",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Error handlers
    app.add_exception_handler(AgentGateError, agentgate_error_handler)

    # Health check
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "billing"}

    # Routers
    app.include_router(accounts_router)
    app.include_router(transactions_router)
    app.include_router(stripe_router)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("billing.main:app", host="0.0.0.0", port=8002, reload=True)
