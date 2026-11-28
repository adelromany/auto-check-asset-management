"""Application factory. No business logic lives here."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app import auth, config
from app.dependencies import current_user, get_store
from app.routers import (
    agent,
    dashboard,
    diag,
    devices,
    documents,
    handovers,
    health,
    maintenance,
    pages,
    snipeit,
)
from app.security.csrf import CsrfMiddleware
from app.security.headers import SecurityHeadersMiddleware
from app.security.ratelimit import RateLimitMiddleware
from app.security.startup import validate_startup_config
from app.logging_config import configure_logging
from app.middleware.request_id import RequestIdMiddleware
from app.request_context import request_id_var

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(application):
    task = None
    if config.PENDING_USER_CHECK_ENABLED:
        from app.clients.snipeit import ServiceAccountProvider, SnipeItClient
        from app.db.engine import get_sessionmaker
        from app.services.pending_users import pending_user_loop

        def client_factory():
            return SnipeItClient(config.SNIPEIT_URL, ServiceAccountProvider(config.SNIPEIT_TOKEN), timeout=config.SNIPEIT_TIMEOUT_SECONDS)

        task = asyncio.create_task(pending_user_loop(get_sessionmaker(), client_factory, hours=config.PENDING_USER_CHECK_HOURS))
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def create_app() -> FastAPI:
    configure_logging()
    validate_startup_config()
    application = FastAPI(title=config.APP_NAME, docs_url=None, redoc_url=None, lifespan=_lifespan)
    application.add_exception_handler(Exception, _internal_error)
    application.add_exception_handler(StarletteHTTPException, _http_error)
    application.add_exception_handler(RequestValidationError, _validation_error)
    static_dir = Path(__file__).resolve().parents[1] / "static"
    application.mount("/static", StaticFiles(directory=static_dir), name="static")
    # Added inner-to-outer: the session must exist before CSRF reads it, and
    # the header middleware must wrap every response, including errors.
    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(CsrfMiddleware)
    application.add_middleware(
        SessionMiddleware,
        secret_key=config.SESSION_SECRET,
        https_only=config.HTTPS_ONLY,
        same_site="lax",
        max_age=3600,
    )
    # Added last so the security headers wrap every response, including the
    # error responses the request-id middleware renders for crashed requests.
    application.add_middleware(RequestIdMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)
    application.include_router(auth.router)
    application.include_router(pages.router)
    application.include_router(agent.router)
    application.include_router(handovers.router)
    application.include_router(maintenance.router)
    application.include_router(devices.router)
    application.include_router(documents.router)
    application.include_router(dashboard.router)
    application.include_router(snipeit.router)
    application.include_router(health.router)
    application.include_router(diag.router)
    database_scheme = urlsplit(config.DATABASE_URL).scheme or "unknown"
    snipeit_host = urlsplit(
        config.SNIPEIT_URL if "://" in config.SNIPEIT_URL
        else f"http://{config.SNIPEIT_URL}"
    ).hostname or "unconfigured"
    logger.info(
        "startup database_dialect=%s sso_enabled=%s snipeit_host=%s",
        database_scheme,
        str(config.SSO_ENABLED).lower(),
        snipeit_host,
    )
    if not config.SSO_ENABLED:
        logger.warning("SSO_ENABLED=false; authentication bypass is enabled")
    return application


async def _internal_error(request: Request, exc: Exception) -> Response:
    logger.exception("unhandled_request_error exception_type=%s", type(exc).__name__)
    if _wants_html(request):
        return _html_error(request, status=500, headline="Something went wrong")
    return JSONResponse(
        {"detail": "Internal server error", "request_id": request_id_var.get()},
        status_code=500,
    )


def _wants_html(request: Request) -> bool:
    """A browser navigation (Accept: text/html) gets an HTML error page.

    API and fetch calls (Accept: */* or application/json) keep JSON errors.
    """
    accept = request.headers.get("accept", "")
    first = accept.split(",")[0].strip().lower() if accept else ""
    return first.startswith("text/html")


def _html_error(request: Request, *, status: int, headline: str) -> HTMLResponse:
    from app.routers.pages import templates

    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={
            "page_title": headline,
            "status": status,
            "headline": headline,
            "detail": "",
            "request_id": request_id_var.get(),
        },
        status_code=status,
    )


async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
    if _wants_html(request):
        headlines = {
            404: "Page not found",
            403: "Not allowed",
            401: "Sign-in required",
            500: "Something went wrong",
        }
        return _html_error(
            request,
            status=exc.status_code,
            headline=headlines.get(exc.status_code, "Something went wrong"),
        )
    detail = exc.detail
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        {"detail": detail},
        status_code=exc.status_code,
        headers=headers,
    )


async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
    if _wants_html(request):
        return _html_error(
            request, status=422, headline="The form had invalid values"
        )
    return JSONResponse(
        {"detail": jsonable(exc.errors()), "request_id": request_id_var.get()},
        status_code=422,
    )


def jsonable(errors: list) -> list:
    """Validation errors contain exceptions; strip the non-JSON parts."""
    safe = []
    for error in errors:
        safe.append(
            {
                key: error.get(key)
                for key in ("loc", "msg", "type", "input")
                if key in error
            }
        )
    return safe


app = create_app()

# Re-exports for `import main`-style / legacy access (see root main.py).
__all__ = ["app", "create_app", "config", "auth", "current_user", "get_store",
           "oauth", "SSO_ENABLED", "DEV_USER"]

oauth = auth.oauth
SSO_ENABLED = config.SSO_ENABLED
DEV_USER = config.DEV_USER
