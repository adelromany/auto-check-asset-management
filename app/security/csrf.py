"""CSRF and Origin protection for session-authenticated writes (SEC-11).

The token lives in the signed session cookie. ``GET /api/me`` returns it so
the page modules can send it back in ``X-CSRF-Token``. A request that carries
an ``Origin`` header must also come from this application's origin.

The agent submit endpoint is deliberately outside the protected prefixes: the
agent authenticates with a short code, not a cookie, so it has no session
token to send. See ``docs/OPEN_QUESTIONS.md`` for the remaining gap.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse

from app import config

PROTECTED_PREFIXES = ("/api/handovers", "/api/dashboard")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
TOKEN_KEY = "csrf_token"
HEADER_NAME = "x-csrf-token"


def get_or_create_token(request: Request) -> str:
    """Return the session's CSRF token, creating it on first use."""
    token = request.session.get(TOKEN_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[TOKEN_KEY] = token
    return token


def _origin_is_allowed(origin: str, allowed: set[str]) -> bool:
    if not origin or origin == "null":
        return False
    parsed = urlsplit(origin)
    return bool(parsed.scheme in {"http", "https"} and parsed.netloc in allowed)


def _token_matches(expected: str | None, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    return secrets.compare_digest(expected, provided)


class CsrfMiddleware:
    """Reject unsafe requests to protected prefixes without a valid token."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        if method in SAFE_METHODS or not path.startswith(PROTECTED_PREFIXES):
            await self.app(scope, receive, send)
            return

        # With SSO disabled there is no authenticated session cookie to
        # protect; the development bypass is already loudly warned about.
        if not config.SSO_ENABLED:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        session = scope.get("session") or {}
        expected = session.get(TOKEN_KEY)

        if not _token_matches(expected, headers.get(HEADER_NAME)):
            response = JSONResponse(
                {"detail": "CSRF token missing or invalid"}, status_code=403
            )
            await response(scope, receive, send)
            return

        origin = headers.get("origin")
        if origin and not _origin_is_allowed(origin, _allowed_origins_from_scope(scope)):
            response = JSONResponse({"detail": "Origin not allowed"}, status_code=403)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def _allowed_origins_from_scope(scope) -> set[str]:
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }
    host = headers.get("host", "")
    allowed = {host} if host else set()

    app_host = (config.APP_HOST or "").strip()
    if app_host:
        parsed = urlsplit(app_host if "://" in app_host else f"//{app_host}")
        if parsed.netloc:
            allowed.add(parsed.netloc)
    return allowed
