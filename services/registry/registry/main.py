"""Registry service — FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from openai import AsyncOpenAI

from ag_common.config import RegistryConfig
from ag_common.errors import AgentGateError, agentgate_error_handler
from ag_db.session import create_engine_and_session

from registry.routes.agents import router as agents_router

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize DB engine and OpenAI client on startup; tear down on shutdown."""
    config = RegistryConfig()

    engine, session_factory = create_engine_and_session(
        database_url=config.database_url,
        echo=config.environment == "development",
    )
    app.state.session_factory = session_factory

    openai_client = AsyncOpenAI(api_key=config.openai_api_key)
    app.state.openai_client = openai_client

    log.info(
        "registry.startup",
        environment=config.environment,
        database=config.database_url.split("@")[-1] if "@" in config.database_url else "***",
    )

    yield

    await engine.dispose()
    await openai_client.close()
    log.info("registry.shutdown")


def create_app() -> FastAPI:
    """Build and return the Registry FastAPI application."""
    app = FastAPI(
        title="AgentGate Registry",
        description="Internal agent catalog and semantic search service",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Error handlers
    app.add_exception_handler(AgentGateError, agentgate_error_handler)

    # Routes
    app.include_router(agents_router)

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run("registry.main:app", host="0.0.0.0", port=8001, reload=True)
