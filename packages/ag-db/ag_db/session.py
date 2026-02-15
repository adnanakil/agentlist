"""Async database session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine_and_session(
    database_url: str,
    echo: bool = False,
    pool_size: int = 10,
    max_overflow: int = 20,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create and return an async engine and session factory."""
    global _engine, _session_factory
    _engine = create_async_engine(
        database_url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine, _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session. Use as a FastAPI dependency."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call create_engine_and_session first.")
    async with _session_factory() as session:
        yield session
