"""Shared FastAPI dependencies: session store, database session, current user."""

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.clients.snipeit import ServiceAccountProvider, SnipeItClient
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


async def get_snipeit_client(
    user=Depends(current_user),
) -> AsyncIterator[SnipeItClient]:
    """One Snipe-IT client per request; always closed, even on error."""
    client = SnipeItClient(
        config.SNIPEIT_URL,
        ServiceAccountProvider(config.SNIPEIT_TOKEN),
        timeout=config.SNIPEIT_TIMEOUT_SECONDS,
        engineer_email=(user or {}).get("email") or "",
    )
    try:
        yield client
    finally:
        await client.aclose()
