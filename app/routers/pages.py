"""HTML pages + page-support endpoints.

Pages are server-rendered so the first paint already shows real data; the
vanilla JS modules only refresh the same data when the filters change.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.dependencies import current_user, get_session
from app.domain.recipient_identity import detect_recipient
from app.domain.handover_rules import stalled_by_age
from app.domain.stages import HandoverStatus
from app import config
from app.domain.errors import HandoverNotFound
from app.security.csrf import get_or_create_token
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
    report = await service.latest_agent_report(handover_id)
    detected_user = (
        detect_recipient(report.payload, view.handover.engineer_email)
        if report is not None
        else None
    )
    age_stalled = (
        view.handover.status not in (HandoverStatus.COMPLETED.value, HandoverStatus.CANCELLED.value)
        and stalled_by_age(
            view.handover.updated_at,
            datetime.now(timezone.utc),
            config.STALL_HOURS,
        )
    )
    display_status = HandoverStatus.STALLED.value if age_stalled else view.handover.status

    return templates.TemplateResponse(
        request=request,
        name="handover_detail.html",
        context={
            "page_title": f"Handover {view.handover.device_serial}",
            "handover": view.handover,
            "stages": view.stages,
            "events": view.events,
            "missing": view.missing_steps,
            "detected_user": detected_user,
            "display_status": display_status,
            "stalled_by_age_message": (
                f"No activity for {config.STALL_HOURS} hours" if age_stalled else None
            ),
        },
    )


@router.get("/api/me")
async def me(
    request: Request,
    response: Response,
    user=Depends(current_user),
):
    token = get_or_create_token(request)
    response.headers["X-CSRF-Token"] = token
    return {"name": user.get("name"), "email": user.get("email"), "sso": config.SSO_ENABLED}
