"""Shared FastAPI dependencies: session store + current user."""

from fastapi import HTTPException, Request

from app import config
from app.services.sessions import SessionStore

_default_store = SessionStore(ttl_seconds=config.SESSION_TTL_SECONDS)


def get_store() -> SessionStore:
    """Injectable session store (override in tests via dependency_overrides)."""
    return _default_store


def current_user(request: Request):
    if not config.SSO_ENABLED:
        return config.DEV_USER
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user
