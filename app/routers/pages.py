"""HTML pages + page-support endpoints."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import config
from app.dependencies import current_user

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if config.SSO_ENABLED and not request.session.get("user"):
        return RedirectResponse("/login")
    host = config.APP_HOST or f"http://{request.headers.get('host', 'localhost:8080')}"

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_host": host,
        },
    )


@router.get("/api/me")
async def me(user=Depends(current_user)):
    return {"name": user.get("name"), "email": user.get("email"), "sso": config.SSO_ENABLED}
