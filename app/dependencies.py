"""Shared FastAPI dependencies: session store, database session, current user."""

from collections.abc import AsyncIterator

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.db.engine import get_sessionmaker
from app.services.sessions import SessionStore

_default_store = SessionStore(ttl_seconds=config.SESSION_TTL_SECONDS)


def get_store() -> SessionStore:
    """Injectable session store (override in tests via dependency_overrides)."""
    return _default_store


async def get_session() -> AsyncIterator[AsyncSession]:
    """One database session per request; commit on success, rollback on error.

    This is the only place a transaction is committed, so services and
    repositories never manage transactions themselves.
    """
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def current_user(request: Request):
    if not config.SSO_ENABLED:
        return config.DEV_USER
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user
