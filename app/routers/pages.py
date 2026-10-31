"""HTML pages + page-support endpoints.

Pages are server-rendered so the first paint already shows real data; the
vanilla JS modules only refresh the same data when the filters change.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.dependencies import current_user, get_session
from app.domain.errors import HandoverNotFound
from app.services.dashboard import DashboardService
from app.services.handovers import HandoverService

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _login_redirect(request: Request) -> RedirectResponse | None:
    if config.SSO_ENABLED and not request.session.get("user"):
        return RedirectResponse("/login")
    return None


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect
    host = config.APP_HOST or f"http://{request.headers.get('host', 'localhost:8080')}"

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_host": host,
        },
    )


@router.get("/handovers", response_class=HTMLResponse)
async def handovers_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect

    dashboard = DashboardService(session)
    rows = await dashboard.rows(page=1, page_size=100)
    summary = await dashboard.summary()
    return templates.TemplateResponse(
        request=request,
        name="handovers.html",
        context={
            "page_title": "Handovers",
            "rows": rows.items,
            "total": rows.total,
            "summary": summary,
        },
    )


@router.get("/handovers/{handover_id}", response_class=HTMLResponse)
async def handover_page(
    handover_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect

    service = HandoverService(session)
    try:
        view = await service.get_detail(handover_id)
    except HandoverNotFound as exc:
        raise HTTPException(status_code=404, detail="Handover not found") from exc

    return templates.TemplateResponse(
        request=request,
        name="handover_detail.html",
        context={
            "page_title": f"Handover {view.handover.device_serial}",
            "handover": view.handover,
            "stages": view.stages,
            "events": view.events,
            "missing": view.missing_steps,
        },
    )


@router.get("/api/me")
async def me(user=Depends(current_user)):
    return {"name": user.get("name"), "email": user.get("email"), "sso": config.SSO_ENABLED}
