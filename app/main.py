"""Application factory. No business logic lives here."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import auth, config
from app.dependencies import current_user, get_store
from app.routers import agent, diag, documents, handovers, health, pages, snipeit


def create_app() -> FastAPI:
    application = FastAPI(title="Snipe-IT Onboarding", docs_url=None, redoc_url=None)
    application.mount("/static", StaticFiles(directory="static"), name="static")
    application.add_middleware(
        SessionMiddleware,
        secret_key=config.SESSION_SECRET,
        https_only=config.HTTPS_ONLY,
        same_site="lax",
        max_age=3600,
    )
    application.include_router(auth.router)
    application.include_router(pages.router)
    application.include_router(agent.router)
    application.include_router(handovers.router)
    application.include_router(documents.router)
    application.include_router(snipeit.router)
    application.include_router(health.router)
    application.include_router(diag.router)
    return application


app = create_app()

# Re-exports for `import main`-style / legacy access (see root main.py).
__all__ = ["app", "create_app", "config", "auth", "current_user", "get_store",
           "oauth", "SSO_ENABLED", "DEV_USER"]

oauth = auth.oauth
SSO_ENABLED = config.SSO_ENABLED
DEV_USER = config.DEV_USER
