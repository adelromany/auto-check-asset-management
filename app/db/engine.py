"""Lazy async engine and session factory.

Nothing here connects to a database at import time: the engine is created on
the first ``get_engine()`` call. The characterization tests rely on importing
the app without touching a database.
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app import config

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory bound to the lazy engine."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, autoflush=False
        )
    return _sessionmaker


async def dispose_engine() -> None:
    """Dispose the engine and forget it (tests and shutdown)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
