"""HTML screens + page-support endpoints.

The review split the single page into distinct screens:

- ``/dashboard``  read-only overview: counts and recent cases
- ``/new``        registration form for a new case
- ``/cases``      the case list with search and status filters
- ``/cases/{id}`` the case board
- ``/cases/{id}/history`` the append-only audit trail
- ``/`` and ``/device-check`` the agent device check

``/`` keeps serving the device check because the agent script, bookmarks and
users still open it; ``/device-check`` is the explicit name. The two old case
page URLs redirect permanently so links and logs keep working.

Pages are server-rendered so the first paint already shows real data; the
vanilla JS modules only refresh the same data when a filter changes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.dependencies import current_user, get_session
from app.domain.errors import HandoverNotFound
from app.domain.handover_rules import stalled_by_age
from app.domain.recipient_identity import detect_recipient
from app.domain.stages import HandoverStatus
from app.dto.dashboard import DashboardSummaryOut
from app.security.csrf import get_or_create_token
from app.services.dashboard import DashboardService
from app.services.handovers import HandoverService

router = APIRouter()
templates = Jinja2Templates(directory="templates")

DASHBOARD_RECENT = 6
DASHBOARD_ATTENTION = 5
CASES_PAGE_SIZE = 100


def _login_redirect(request: Request) -> RedirectResponse | None:
    if config.SSO_ENABLED and not request.session.get("user"):
        return RedirectResponse("/login")
    return None


def _legacy_redirect(path: str, query: str = "") -> RedirectResponse:
    """Permanent move for a page path; the query string is preserved."""
    target = path + (f"?{query}" if query else "")
    return RedirectResponse(target, status_code=308)


def _status_rows(summary) -> list[dict[str, str | int]]:
    return [
        {"status": status, "count": summary.by_status.get(status, 0)}
        for status in (
            HandoverStatus.DRAFT.value,
            HandoverStatus.IN_PROGRESS.value,
            HandoverStatus.STALLED.value,
            HandoverStatus.COMPLETED.value,
            HandoverStatus.CLOSED_WITH_GAPS.value,
            HandoverStatus.CANCELLED.value,
        )
    ]


# -- dashboard ---------------------------------------------------------------


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect

    try:
        dashboard = DashboardService(session)
        summary = await dashboard.summary()
        recent_page = await dashboard.rows(page=1, page_size=DASHBOARD_RECENT)
        recent = recent_page.items
        attention_page = await dashboard.rows(
            status=HandoverStatus.STALLED.value, page_size=DASHBOARD_ATTENTION
        )
        attention = attention_page.items
    except OperationalError:
        summary = DashboardSummaryOut()
        recent = []
        attention = []

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "page_title": "Dashboard",
            "active_nav": "dashboard",
            "summary": summary,
            "recent": recent,
            "attention": attention,
            "status_rows": _status_rows(summary),
            "stall_hours": config.STALL_HOURS,
        },
    )


# -- registration ------------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
async def new_case_page(request: Request):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="new_case.html",
        context={
            "page_title": "New case",
            "active_nav": "new",
        },
    )


# -- cases list --------------------------------------------------------------


@router.get("/cases", response_class=HTMLResponse)
async def cases_page(
    request: Request,
    q: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect

    try:
        status = HandoverStatus(status).value if status else None
    except ValueError:
        status = None
    kind = kind if kind in ("handover", "maintenance") else None
    query = (q or "").strip()[:100]

    dashboard = DashboardService(session)
    rows = await dashboard.rows(
        status=status,
        kind=kind,
        q=query or None,
        page_size=CASES_PAGE_SIZE,
    )
    summary = await dashboard.summary()
    return templates.TemplateResponse(
        request=request,
        name="cases.html",
        context={
            "page_title": "Cases",
            "active_nav": "cases",
            "rows": rows.items,
            "total": rows.total,
            "summary": summary,
            "query": query,
            "active_status": status or "",
            "active_kind": kind or "",
            "filtered": bool(query or status or kind),
            "stall_hours": config.STALL_HOURS,
        },
    )


# -- case board and history --------------------------------------------------


async def _case_view(handover_id: uuid.UUID, session: AsyncSession):
    service = HandoverService(session)
    try:
        view = await service.get_detail(handover_id)
    except HandoverNotFound as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    report = await service.latest_agent_report(handover_id)
    detected_user = (
        detect_recipient(report.payload, view.handover.engineer_email)
        if report is not None
        else None
    )
    age_stalled = (
        view.handover.status
        not in (
            HandoverStatus.COMPLETED.value,
            HandoverStatus.CANCELLED.value,
            HandoverStatus.CLOSED_WITH_GAPS.value,
        )
        and stalled_by_age(
            view.handover.updated_at,
            datetime.now(timezone.utc),
            config.STALL_HOURS,
        )
    )
    display_status = (
        HandoverStatus.STALLED.value if age_stalled else view.handover.status
    )
    return view, report, detected_user, display_status, age_stalled


@router.get("/cases/{handover_id}", response_class=HTMLResponse)
async def case_page(
    handover_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect

    view, report, detected_user, display_status, age_stalled = await _case_view(
        handover_id, session
    )
    return templates.TemplateResponse(
        request=request,
        name="handover_detail.html",
        context={
            "page_title": f"Case {view.handover.device_serial}",
            "active_nav": "cases",
            "handover": view.handover,
            "stages": view.stages,
            "events": view.events[-5:],
            "event_total": len(view.events),
            "missing": view.missing_steps,
            "detected_user": detected_user,
            "agent_report": report.payload if report is not None else None,
            "display_status": display_status,
            "stalled_by_age_message": (
                f"No activity for {config.STALL_HOURS} hours" if age_stalled else None
            ),
        },
    )


def _format_event_sentence(etype: str, detail: dict, actor_name: str) -> str:
    if etype == "handover_created":
        return "Case opened"
    elif etype == "operation_recorded":
        op = detail.get("operation", "")
        op_label = op.replace("_", " ").title()
        outcome = detail.get("outcome", "")
        reason = detail.get("reason", "")
        if outcome == "passed":
            return f"{actor_name} completed {op_label}"
        elif outcome == "not_done":
            return f"{actor_name} marked {op_label} as not done: {reason}"
        elif outcome == "failed":
            return f"{op_label} failed: {reason}"
        elif outcome == "retry":
            return f"{actor_name} retried {op_label}"
        return f"{actor_name} recorded {op_label}"
    elif etype == "agent_report_received":
        return "Device check received: serial matched"
    elif etype == "software_check_evaluated":
        return "Software checks evaluated"
    elif etype == "software_check_deferred":
        return "Software checks deferred"
    elif etype == "software_check_overridden":
        return f"{actor_name} overridden software check: {detail.get('reason', '')}"
    elif etype == "recipient_identity_detected":
        return f"Recipient detected from device: {detail.get('username', '')}"
    elif etype == "recipient_identity_blocked":
        return "Recipient blocked: domain user not found"
    elif etype == "snipeit_recipient_confirmed":
        return f"{actor_name} confirmed recipient in Snipe-IT"
    elif etype == "snipeit_checkout_performed":
        return "Checkout verified in Snipe-IT"
    elif etype == "document_uploaded":
        return "Signed paper scan attached"
    elif etype == "snipeit_document_pushed":
        return "Changes pushed to Snipe-IT"
    elif etype == "handover_closed":
        return "Case closed with gaps"
    elif etype == "handover_reopened":
        return "Case reopened"
    elif etype == "handover_cancelled":
        return "Case cancelled"
    return etype.replace("_", " ").capitalize()


def _build_timeline_groups(events: list) -> list[dict]:
    import json
    if not events:
        return []

    sorted_events = sorted(
        events,
        key=lambda e: getattr(e, "created_at", getattr(e, "at", None)) or datetime.min,
        reverse=True,
    )

    coalesced: list[dict] = []
    for ev in sorted_events:
        dt = getattr(ev, "created_at", getattr(ev, "at", None))
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt)
            except Exception:
                dt = datetime.now(timezone.utc)
        elif dt is None:
            dt = datetime.now(timezone.utc)

        actor_raw = getattr(ev, "actor", "") or "System"
        actor_name = (
            actor_raw.split("<")[0].strip() or actor_raw.split("@")[0] or "Engineer"
        )
        detail = getattr(ev, "detail", {}) or {}
        etype = getattr(ev, "type", "")
        sentence = _format_event_sentence(etype, detail, actor_name)
        detail_json = json.dumps(detail, indent=2) if detail else ""

        if coalesced:
            prev = coalesced[-1]
            time_diff = abs((prev["dt"] - dt).total_seconds())
            if prev["actor_raw"] == actor_raw and time_diff <= 2:
                if sentence not in prev["sentence"]:
                    prev["sentence"] = f"{prev['sentence']}; {sentence}"
                if detail_json:
                    prev["details_json"] = (prev["details_json"] + "\n" + detail_json).strip()
                continue

        coalesced.append({
            "dt": dt,
            "date": dt.strftime("%B %d, %Y") if hasattr(dt, "strftime") else str(dt)[:10],
            "time": dt.strftime("%H:%M:%S") if hasattr(dt, "strftime") else str(dt)[11:19],
            "actor_raw": actor_raw,
            "actor": actor_raw,
            "actor_display": actor_name,
            "sentence": sentence,
            "details_json": detail_json,
        })

    groups_dict: dict[str, list[dict]] = {}
    for entry in coalesced:
        d = entry["date"]
        if d not in groups_dict:
            groups_dict[d] = []
        groups_dict[d].append(entry)

    return [{"date": d, "entries": entries} for d, entries in groups_dict.items()]


@router.get("/cases/{handover_id}/history", response_class=HTMLResponse)
async def case_history_page(
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
        raise HTTPException(status_code=404, detail="Case not found") from exc

    timeline_groups = _build_timeline_groups(view.events)

    return templates.TemplateResponse(
        request=request,
        name="case_history.html",
        context={
            "page_title": f"History {view.handover.device_serial}",
            "active_nav": "cases",
            "handover": view.handover,
            "timeline_groups": timeline_groups,
            "timeline_count": len(view.events),
        },
    )


# -- device check ------------------------------------------------------------


def _device_check(request: Request):
    host = config.APP_HOST or f"http://{request.headers.get('host', 'localhost:8080')}"
    return templates.TemplateResponse(
        request=request,
        name="device_check.html",
        context={"app_host": host, "page_title": "Device check", "active_nav": "device"},
    )


@router.get("/", response_class=HTMLResponse)
async def home_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect

    if request.query_params.get("handover_id"):
        query = str(request.url.query)
        target = f"/device-check?{query}" if query else "/device-check"
        return RedirectResponse(target, status_code=307)

    return await dashboard_page(request, session)


@router.get("/device-check", response_class=HTMLResponse)
async def device_check_page(request: Request):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect
    return _device_check(request)


# -- compatibility: the old page URLs --------------------------------


@router.get("/handovers", response_class=HTMLResponse)
async def legacy_cases_page(request: Request):
    return _legacy_redirect("/cases", request.url.query)


@router.get("/handovers/{handover_id}", response_class=HTMLResponse)
async def legacy_case_page(handover_id: uuid.UUID, request: Request):
    return _legacy_redirect(f"/cases/{handover_id}", request.url.query)


@router.get("/api/me")
async def me(
    request: Request,
    response: Response,
    user=Depends(current_user),
):
    token = get_or_create_token(request)
    response.headers["X-CSRF-Token"] = token
    return {"name": user.get("name"), "email": user.get("email"), "sso": config.SSO_ENABLED}
