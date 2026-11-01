"""Application factory. No business logic lives here."""

import logging
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import auth, config
from app.dependencies import current_user, get_store
from app.routers import (
    agent,
    dashboard,
    diag,
    documents,
    handovers,
    health,
    pages,
    printing,
    snipeit,
)
from app.security.csrf import CsrfMiddleware
from app.security.headers import SecurityHeadersMiddleware
from app.security.ratelimit import RateLimitMiddleware
from app.security.startup import validate_startup_config
from app.logging_config import configure_logging
from app.middleware.request_id import RequestIdMiddleware
from app.request_context import request_id_var
from app.services import printing as print_service

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging()
    validate_startup_config()
    application = FastAPI(title="Snipe-IT Onboarding", docs_url=None, redoc_url=None)
    application.add_exception_handler(Exception, _internal_error)
    application.mount("/static", StaticFiles(directory="static"), name="static")
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
    application.add_middleware(SecurityHeadersMiddleware)
    # Added last so the server-generated id wraps every other middleware.
    application.add_middleware(RequestIdMiddleware)
    print_service.setup_logging()          # honors PRINT_LOG_FILE
    application.include_router(auth.router)
    application.include_router(pages.router)
    application.include_router(agent.router)
    application.include_router(handovers.router)
    application.include_router(documents.router)
    application.include_router(dashboard.router)
    application.include_router(snipeit.router)
    application.include_router(printing.router)
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


async def _internal_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_request_error exception_type=%s", type(exc).__name__)
    return JSONResponse(
        {"detail": "Internal server error", "request_id": request_id_var.get()},
        status_code=500,
    )


app = create_app()

# Re-exports for `import main`-style / legacy access (see root main.py).
__all__ = ["app", "create_app", "config", "auth", "current_user", "get_store",
           "oauth", "SSO_ENABLED", "DEV_USER"]

oauth = auth.oauth
SSO_ENABLED = config.SSO_ENABLED
DEV_USER = config.DEV_USER
