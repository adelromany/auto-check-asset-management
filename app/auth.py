"""Entra ID SSO routes: /login, /auth/callback, /logout."""

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app import config

oauth = OAuth()
oauth.register(
    name="entra",
    client_id=config.AZURE_CLIENT_ID,
    client_secret=config.AZURE_CLIENT_SECRET,
    server_metadata_url=(
        f"https://login.microsoftonline.com/{config.AZURE_TENANT_ID}"
        "/v2.0/.well-known/openid-configuration"
    ),
    client_kwargs={
        "scope": "openid profile email",
        "token_endpoint_auth_method": "client_secret_post",
    },
)

router = APIRouter()


@router.get("/login")
async def login(request: Request):
    if not config.SSO_ENABLED:
        return RedirectResponse("/")
    return await oauth.entra.authorize_redirect(request, config.REDIRECT_URI)


@router.get("/auth/callback")
async def auth_callback(request: Request):
    if not config.SSO_ENABLED:
        return RedirectResponse("/")
    token = await oauth.entra.authorize_access_token(request)
    c = token["userinfo"]
    request.session["user"] = {
        "name": c.get("name"),
        "email": c.get("preferred_username"),
    }
    return RedirectResponse("/")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")
