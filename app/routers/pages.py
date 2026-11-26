"""HTML screens + page-support endpoints.

Four destinations (owner decision, 2026-11):

- ``/``             Dashboard: handovers and maintenance in one view
- ``/handovers``    monitor and register device handovers
- ``/maintenance``  register and monitor repairs and devices at vendors
- ``/sync``         the agent flow: check a device without opening it

Case pages live under their screen: ``/handovers/{id}`` and
``/maintenance/{id}``, each with a ``/history`` page. The old URLs
(``/dashboard``, ``/new``, ``/cases...``, ``/device-check``) answer 308 to the
new ones with the query string preserved, so bookmarks and logs keep working.

Pages are server-rendered so the first paint already shows real data; the
vanilla JS modules only refresh the same data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.dependencies import current_user, get_session
from app.domain.catalog import CaseKind, Operation, OPERATION_TITLES, lanes_for
from app.domain.errors import HandoverNotFound
from app.domain.handover_rules import (
    StageState,
    case_outcome,
    case_warnings,
    missing_parts,
    stalled_by_age,
)
from app.domain.maintenance_rules import (
    MAINTENANCE_OVERDUE_DAYS,
    MaintenanceState,
    derive_maintenance_state,
    is_overdue,
    maintenance_label,
    turnaround_days,
)
from app.domain.stages import StageStatus, HandoverStatus
from app.dto.dashboard import DashboardSummaryOut
from app.repositories.maintenance import MaintenanceRepository
from app.security.csrf import get_or_create_token
from app.services.dashboard import DashboardService
from app.services.handovers import HandoverService, stage_states

router = APIRouter()
templates = Jinja2Templates(
    directory=Path(__file__).resolve().parents[2] / "templates"
)

ROWS_PAGE_SIZE = 100
ACTIVE_STATUSES = (
    HandoverStatus.DRAFT.value,
    HandoverStatus.IN_PROGRESS.value,
    HandoverStatus.STALLED.value,
)


def _login_redirect(request: Request) -> RedirectResponse | None:
    if config.SSO_ENABLED and not request.session.get("user"):
        return RedirectResponse("/login")
    return None


def _redirect308(path: str, query: str = "") -> RedirectResponse:
    """Permanent move for a page path; the query string is preserved."""
    target = path + (f"?{query}" if query else "")
    return RedirectResponse(target, status_code=308)


def _common_ctx(request: Request, title: str, nav: str) -> dict:
    return {
        "page_title": title,
        "active_nav": nav,
        "request": request,
        "app_host": config.APP_HOST
        or f"http://{request.headers.get('host', 'localhost:8080')}",
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_days(value: datetime | None) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, (_now() - value).days)


def _display_status(handover) -> str:
    """Show the age-based stalled state even though the DB keeps in_progress."""
    if handover.status in (
        HandoverStatus.DRAFT.value,
        HandoverStatus.IN_PROGRESS.value,
    ):
        if stalled_by_age(handover.updated_at, _now(), config.STALL_HOURS):
            return HandoverStatus.STALLED.value
    return handover.status


# -- shared row shaping -------------------------------------------------------


def _row_states(handover) -> list[tuple[str, str]]:
    return [
        (state.stage.value, state.status.value) for state in stage_states(handover)
    ]


def _handover_column(row: dict) -> str:
    """The board column of a handover, derived from its operations."""
    states = dict(row["states"])
    if row["status"] in (
        HandoverStatus.COMPLETED.value,
        HandoverStatus.CLOSED_WITH_GAPS.value,
        HandoverStatus.CANCELLED.value,
    ):
        return "done"
    if states.get("checkout") == StageStatus.PASSED.value:
        return "paperwork"
    if states.get("device_prepared") == StageStatus.PASSED.value or (
        states.get("recipient_check") == StageStatus.PASSED.value
    ):
        return "assigned"
    return "preparing"


def _row_context(handover) -> dict:
    states = _row_states(handover)
    maintenance_state = handover.maintenance_state
    if (
        (handover.kind or CaseKind.HANDOVER.value) == CaseKind.MAINTENANCE.value
        and handover.stages
    ):
        maintenance_state = derive_maintenance_state(dict(states)).value
    rows_by_stage = {row.stage: row for row in handover.stages}
    reasons = {
        stage: (row.reason or "")
        for stage, row in rows_by_stage.items()
        if row.reason
    }
    handover_states = [StageState(Operation(stage), StageStatus(state), reason) for stage, state, reason in (
        (row.stage, row.status, row.reason) for row in rows_by_stage.values()
    )]
    ctx = {
        "id": handover.id,
        "kind": handover.kind or CaseKind.HANDOVER.value,
        "serial": handover.device_serial,
        "ticket_ref": handover.ticket_ref,
        "model": handover.device_model or "",
        "company": handover.device_company or "",
        "engineer_name": handover.engineer_name or handover.engineer_email,
        "recipient": (
            handover.recipient_snipeit_name
            or handover.recipient_snipeit_username
            or handover.recipient_reported_username
        ),
        "recipient_company": getattr(handover, "recipient_company", None),
        "status": handover.status,
        "outcome": case_outcome(handover_states, recipient_mode=handover.recipient_mode, cancelled=handover.status == "cancelled").value,
        "missing": missing_parts(handover_states),
        "warnings": case_warnings(
            handover.device_company,
            getattr(handover, "recipient_company", None),
        ),
        "display_status": _display_status(handover),
        "maintenance_state": maintenance_state,
        "states": states,
        "states_map": {stage: status for stage, status in states},
        "reasons": reasons,
        "created_at": handover.created_at,
        "updated_at": handover.updated_at,
        "age_days": _age_days(handover.created_at),
        "maintenance": handover.maintenance,
        "vendor": _vendor_name(handover.maintenance),
        # D5: the "all passed" chip is honest only when every operation passed
        # and there is at least one operation.
        "all_passed": bool(states)
        and all(status == StageStatus.PASSED.value for _, status in states),
    }
    if ctx["kind"] == CaseKind.HANDOVER.value:
        ctx["column"] = _handover_column(ctx)
    return ctx


async def _list_rows(
    session: AsyncSession, *, kind: str | None = None, status: str | None = None,
    engineer: str | None = None, q: str | None = None,
    outcome: str | None = None, company: str | None = None,
) -> list[dict]:
    service = HandoverService(session)
    items, _total = await service.list(
        kind=kind, status=status, engineer=engineer, q=q, outcome=outcome, company=company,
        page=1, page_size=ROWS_PAGE_SIZE,
    )
    return [_row_context(h) for h in items]


def _state_label(state: str | None) -> str:
    return maintenance_label(state or "")


def _vendor_name(maintenance) -> str:
    if maintenance is None or maintenance.vendor is None:
        return ""
    return maintenance.vendor.name


# -- dashboard ----------------------------------------------------------------


def _attention_from_rows(rows: list[dict]) -> list[dict]:
    """The needs-attention list: one row per case that needs an engineer now."""
    items: list[dict] = []
    for row in rows:
        if row["status"] in (
            HandoverStatus.CANCELLED.value,
            HandoverStatus.COMPLETED.value,
        ):
            continue
        reason = None
        urgency = 9
        failed = [s for s, st in row["states"] if st == StageStatus.FAILED.value]
        not_done = [s for s, st in row["states"] if st == StageStatus.NOT_DONE.value]
        maintenance = row["maintenance"]
        overdue = maintenance is not None and is_overdue(
            sent_date=maintenance.sent_date,
            expected_return_date=maintenance.expected_return_date,
            today=_now().date(),
            returned=maintenance.returned_date is not None,
        )
        if row["display_status"] == HandoverStatus.STALLED.value:
            reason = f"Stalled {config.STALL_HOURS} h"
            urgency = 2
        elif failed:
            reason = f"{OPERATION_TITLES.get(Operation(failed[0]), failed[0])} failed"
            urgency = 0
        elif overdue and row["maintenance_state"] == MaintenanceState.IN_MAINTENANCE.value:
            # An in-flight device has no returned date: days at the vendor run
            # from the send date to today.
            days = (
                (_now().date() - maintenance.sent_date).days
                if maintenance.sent_date is not None
                else None
            )
            reason = (
                f"At vendor {days} days, overdue"
                if days is not None
                else "At vendor, overdue"
            )
            urgency = 1
        elif not_done:
            reason = f"{OPERATION_TITLES.get(Operation(not_done[0]), not_done[0])} not done"
            urgency = 3
        elif row["status"] == HandoverStatus.CLOSED_WITH_GAPS.value:
            reason = "Closed with gaps"
            urgency = 4
        else:
            continue
        items.append({**row, "reason": reason, "urgency": urgency})
    items.sort(key=lambda item: (item["urgency"], item["updated_at"] or item["created_at"]))
    return items[:8]


def _tile_counts(rows: list[dict]) -> dict:
    now = _now()
    week_ago = now - timedelta(days=7)
    handovers = [r for r in rows if r["kind"] == CaseKind.HANDOVER.value]
    maints = [r for r in rows if r["kind"] == CaseKind.MAINTENANCE.value]
    handover_open = [
        r for r in handovers if r["status"] in ACTIVE_STATUSES
    ]
    handover_attention = [
        r
        for r in handovers
        if r["display_status"] == HandoverStatus.STALLED.value
        or r["status"] == HandoverStatus.CLOSED_WITH_GAPS.value
    ]
    needs_maintenance = [
        r for r in maints
        if r["maintenance_state"] in (MaintenanceState.NEEDS_MAINTENANCE.value, None)
        and r["status"] in ACTIVE_STATUSES
    ]
    at_vendor = [
        r for r in maints
        if r["maintenance_state"] == MaintenanceState.IN_MAINTENANCE.value
        and r["status"] in ACTIVE_STATUSES
    ]
    returned_week = [
        r for r in maints
        if r["maintenance_state"] == MaintenanceState.RETURNED.value
        and r["maintenance"] is not None
        and r["maintenance"].returned_date is not None
        and r["maintenance"].returned_date >= week_ago.date()
    ]
    return {
        "handovers_open": len(handover_open),
        "handovers_attention": len(handover_attention),
        "needs_maintenance": len(needs_maintenance),
        "at_vendor": len(at_vendor),
        "returned_week": len(returned_week),
    }


def _bar_rows(counts: dict[str, int]) -> list[dict]:
    """Bar rows with the width already computed (no math in the template)."""
    total = sum(counts.values())
    return [
        {
            "key": key,
            "count": count,
            "pct": round(count * 100 / total) if total else 0,
        }
        for key, count in counts.items()
    ]


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect

    try:
        rows = await _list_rows(session)
        summary = await DashboardService(session).summary()
    except Exception:
        rows = []
        summary = DashboardSummaryOut()

    attention = _attention_from_rows(rows)
    tiles = _tile_counts(rows)
    handover_status = {
        s.value: sum(
            1 for r in rows
            if r["kind"] == CaseKind.HANDOVER.value and r["display_status"] == s.value
        )
        for s in HandoverStatus
    }
    maint_states = {
        state.value: sum(
            1 for r in rows
            if r["kind"] == CaseKind.MAINTENANCE.value
            and r["maintenance_state"] == state.value
        )
        for state in MaintenanceState
    }

    ctx = _common_ctx(request, "Dashboard", "dashboard")
    ctx.update(
        attention=attention,
        tiles=tiles,
        handover_bars=_bar_rows(handover_status),
        maint_bars=_bar_rows(maint_states),
        summary=summary,
        stall_hours=config.STALL_HOURS,
    )
    return templates.TemplateResponse(request=request, name="dashboard.html", context=ctx)


@router.get("/dashboard", response_class=HTMLResponse)
async def legacy_dashboard(request: Request):
    return _redirect308("/", request.url.query)


# -- handovers screen ---------------------------------------------------------


@router.get("/handovers", response_class=HTMLResponse)
async def handovers_page(
    request: Request,
    status: str | None = None,
    engineer: str | None = None,
    q: str | None = None,
    range: str | None = None,
    company: str | None = None,
    outcome: str | None = None,
    new: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect
    status = status if status in [s.value for s in HandoverStatus] else None
    if outcome not in ("complete", "not_complete", "ready") and status:
        outcome = {
            HandoverStatus.COMPLETED.value: "complete",
            HandoverStatus.READY.value: "ready",
        }.get(status, "not_complete")
    query = (q or "").strip()[:100]
    rows = await _list_rows(
        session, kind=CaseKind.HANDOVER.value, engineer=engineer,
        q=query or None,
        outcome=outcome if outcome in ("complete", "not_complete", "ready") else None,
        company=company or None,
    )
    active_range = range if range in ("today", "week", "month") else ""
    if active_range:
        days = {"today": 1, "week": 7, "month": 30}[active_range]
        cutoff = _now() - timedelta(days=days)
        rows = [
            row for row in rows
            if row["created_at"].replace(tzinfo=row["created_at"].tzinfo or timezone.utc)
            >= cutoff
        ]
    engineers = sorted({r["engineer_name"] for r in rows if r["engineer_name"]})
    ctx = _common_ctx(request, "Handovers", "handovers")
    ctx.update(
        rows=rows,
        engineers=engineers,
        active_status=status or "",
        active_engineer=engineer or "",
        active_range=active_range,
        query=query,
        active_company=company or "",
        active_outcome=outcome or "",
        open_new=new == "1",
        stall_hours=config.STALL_HOURS,
    )
    return templates.TemplateResponse(request=request, name="handovers.html", context=ctx)


# -- maintenance screen -------------------------------------------------------


def _maintenance_row_extra(row: dict, *, vendor_warn_days: int = MAINTENANCE_OVERDUE_DAYS) -> dict:
    """Days at vendor and the clock level (ok / warn / overdue)."""
    maintenance = row["maintenance"]
    extra = {
        "days_at_vendor": None,
        "vendor_level": "none",
        "sent_date": None,
        "expected_return_date": None,
        "reference": "",
        "issue": "",
        "vendor": row.get("vendor", ""),
    }
    if maintenance is None:
        return extra
    extra["issue"] = (maintenance.reported_issue or "").split("\n")[0][:80]
    extra["sent_date"] = maintenance.sent_date
    extra["expected_return_date"] = maintenance.expected_return_date
    extra["reference"] = maintenance.reference or ""
    if row["maintenance_state"] == MaintenanceState.IN_MAINTENANCE.value and maintenance.sent_date:
        days = (_now().date() - maintenance.sent_date).days
        extra["days_at_vendor"] = days
        due = maintenance.expected_return_date or (
            maintenance.sent_date + timedelta(days=MAINTENANCE_OVERDUE_DAYS)
        )
        if _now().date() > due:
            extra["vendor_level"] = "overdue"
        elif days >= vendor_warn_days:
            extra["vendor_level"] = "warn"
        else:
            extra["vendor_level"] = "ok"
    return extra


def _vendor_averages(rows: list[dict]) -> dict[str, int]:
    """The average turnaround each vendor achieved on returned devices."""
    sums: dict[str, list[int]] = {}
    for row in rows:
        maintenance = row["maintenance"]
        vendor = _vendor_name(maintenance)
        if not vendor or row["maintenance_state"] != MaintenanceState.RETURNED.value:
            continue
        days = turnaround_days(
            sent_date=maintenance.sent_date,
            returned_date=maintenance.returned_date,
        )
        if days is not None:
            sums.setdefault(vendor, []).append(days)
    return {
        vendor: round(sum(days_list) / len(days_list))
        for vendor, days_list in sums.items()
        if days_list
    }


def _vendor_stats(rows: list[dict]) -> list[dict]:
    """Per vendor: devices at the vendor, average turnaround, overdue count."""
    by_vendor: dict[str, dict] = {}
    for row in rows:
        maintenance = row["maintenance"]
        vendor = _vendor_name(maintenance)
        if not vendor:
            continue
        stats = by_vendor.setdefault(
            vendor, {"name": vendor, "at_vendor": 0, "overdue": 0, "turnarounds": []}
        )
        if row["maintenance_state"] == MaintenanceState.IN_MAINTENANCE.value:
            stats["at_vendor"] += 1
            extra = row.get("extra", {})
            if extra.get("vendor_level") == "overdue":
                stats["overdue"] += 1
        if (
            row["maintenance_state"] == MaintenanceState.RETURNED.value
            and maintenance is not None
        ):
            days = turnaround_days(
                sent_date=maintenance.sent_date,
                returned_date=maintenance.returned_date,
            )
            if days is not None:
                stats["turnarounds"].append(days)
    result = []
    for stats in by_vendor.values():
        turnarounds = stats.pop("turnarounds")
        stats["avg_turnaround"] = (
            round(sum(turnarounds) / len(turnarounds)) if turnarounds else None
        )
        result.append(stats)
    result.sort(key=lambda item: item["name"])
    return result


def _maintenance_group_bars(groups, *, vendor_ids: dict[str, int] | None = None) -> list[dict]:
    """Dashboard group rows with CSP-safe bar percentages."""
    total = sum(group.count for group in groups) or 1
    return [
        {
            "name": group.name,
            "count": group.count,
            "pct": round(group.count * 100 / total),
            "vendor_id": (vendor_ids or {}).get(group.name),
        }
        for group in groups
    ]


@router.get("/maintenance", response_class=HTMLResponse)
async def maintenance_page(
    request: Request,
    vendor: str | None = None,
    company: str | None = None,
    model: str | None = None,
    q: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect
    dashboard = await DashboardService(session).maintenance()
    query = (q or "").strip()[:100]
    devices = dashboard.devices
    if company:
        devices = [item for item in devices if item.company == company]
    if model:
        devices = [item for item in devices if item.model == model]
    if vendor:
        devices = [item for item in devices if (item.vendor or "Not assigned") == vendor]
    if query:
        needle = query.casefold()
        devices = [item for item in devices if needle in item.serial.casefold()]

    vendors = await MaintenanceRepository(session).list_vendors(include_inactive=True)
    vendor_ids = {item.name: item.id for item in vendors}

    def section_bars(section) -> dict[str, list[dict]]:
        return {
            "model": _maintenance_group_bars(section.by_model),
            "company": _maintenance_group_bars(section.by_company),
            "vendor": _maintenance_group_bars(section.by_vendor, vendor_ids=vendor_ids),
        }

    legacy_rows = await _list_rows(session, kind=CaseKind.MAINTENANCE.value)
    vendor_stats = _vendor_stats(legacy_rows)
    ctx = _common_ctx(request, "Maintenance", "maintenance")
    ctx.update(
        dashboard=dashboard,
        vendor_stats=vendor_stats,
        legacy_at_vendor=[
            row for row in legacy_rows
            if row["maintenance_state"] == MaintenanceState.AT_VENDOR.value
        ],
        devices=devices,
        needs_bars=section_bars(dashboard.needs),
        in_bars=section_bars(dashboard.in_maintenance),
        active_company=company or "",
        active_model=model or "",
        active_vendor=vendor or "",
        query=query,
        warn_days=config.MAINT_WARN_DAYS,
        late_days=config.MAINT_LATE_DAYS,
    )
    return templates.TemplateResponse(request=request, name="maintenance.html", context=ctx)


@router.get("/maintenance/devices", response_class=HTMLResponse)
async def maintenance_devices_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect
    rows = await _list_rows(session, kind=CaseKind.MAINTENANCE.value)
    ctx = _common_ctx(request, "Devices", "maintenance_devices")
    ctx.update(rows=rows)
    return templates.TemplateResponse(request=request, name="maintenance_devices.html", context=ctx)


@router.get("/maintenance/vendors", response_class=HTMLResponse)
async def maintenance_vendors_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect
    ctx = _common_ctx(request, "Vendors", "maintenance_vendors")
    return templates.TemplateResponse(request=request, name="maintenance_vendors.html", context=ctx)


# -- sync screen --------------------------------------------------------------


@router.get("/sync", response_class=HTMLResponse)
async def sync_page(
    request: Request,
    handover_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect
    host = config.APP_HOST or f"http://{request.headers.get('host', 'localhost:8080')}"
    ctx = _common_ctx(request, "Sync", "sync")
    ctx.update(app_host=host, back_to_case=await _back_to_case(session, handover_id))
    return templates.TemplateResponse(request=request, name="sync.html", context=ctx)


async def _back_to_case(session: AsyncSession, raw_id: str | None) -> dict | None:
    """The case a device check was opened from (/device-check?handover_id=)."""
    if not raw_id:
        return None
    try:
        case_id = uuid.UUID(raw_id)
    except (ValueError, AttributeError):
        return None
    from app.repositories.handovers import HandoverRepository

    try:
        handover = await HandoverRepository(session).get(case_id)
    except Exception:
        return None
    base = "maintenance" if (handover.kind or "") == CaseKind.MAINTENANCE.value else "handovers"
    return {
        "url": f"/{base}/{handover.id}",
        "serial": handover.device_serial,
    }


@router.get("/device-check", response_class=HTMLResponse)
async def legacy_device_check(request: Request):
    return _redirect308("/sync", request.url.query)


# -- case pages (both kinds) --------------------------------------------------


async def _load_case(session: AsyncSession, handover_id: uuid.UUID):
    service = HandoverService(session)
    try:
        view = await service.get_detail(handover_id)
    except HandoverNotFound as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    return service, view


@router.get("/handovers/{handover_id}", response_class=HTMLResponse)
async def handover_case_page(
    handover_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect
    _service, view = await _load_case(session, handover_id)
    if (view.handover.kind or "handover") != CaseKind.HANDOVER.value:
        return _redirect308(f"/maintenance/{handover_id}")
    return await _case_response(request, view, "handovers", session)


@router.get("/maintenance/{handover_id}", response_class=HTMLResponse)
async def maintenance_case_page(
    handover_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect
    _service, view = await _load_case(session, handover_id)
    if (view.handover.kind or "handover") == CaseKind.HANDOVER.value:
        return _redirect308(f"/handovers/{handover_id}")
    return await _case_response(request, view, "maintenance", session)


async def _case_response(request: Request, view, nav: str, session: AsyncSession):
    handover = view.handover
    service = HandoverService(session)
    report = await service.latest_agent_report(handover.id)
    lanes = lanes_for(handover.kind or "handover")
    vendors = categories = []
    if (handover.kind or "handover") == CaseKind.MAINTENANCE.value:
        repo = MaintenanceRepository(session)
        vendors = await repo.list_destinations()
        categories = await repo.list_diagnosis_categories()

    ctx = _common_ctx(
        request, f"{handover.device_serial}", nav
    )
    ctx.update(
        handover=handover,
        row=_row_context(handover),
        stages=view.stages,
        missing=view.missing_steps,
        agent_report=(report.payload if report is not None else None),
        has_agent_report=report is not None,
        serial_match=(
            report is not None
            and (report.payload.get("serial") or "").strip().upper()
            == (handover.device_serial or "").strip().upper()
        ),
        has_document=bool(handover.documents),
        lanes=lanes,
        maintenance=handover.maintenance,
        vendors=vendors,
        categories=categories,
        event_total=len(view.events),
        stall_hours=config.STALL_HOURS,
        OPERATION_TITLES=OPERATION_TITLES,
    )
    template = "handover_case.html" if nav == "handovers" else "maintenance_case.html"
    if template == "handover_case.html":
        states = [StageState(Operation(stage.stage), StageStatus(stage.status), stage.reason) for stage in view.stages]
        ctx.update(
            outcome=case_outcome(states, recipient_mode=handover.recipient_mode, cancelled=handover.status == "cancelled").value,
            missing_parts=missing_parts(states),
        )
    return templates.TemplateResponse(request=request, name=template, context=ctx)


@router.get("/handovers/{handover_id}/history", response_class=HTMLResponse)
async def handover_case_history(
    handover_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect
    return await _history_response(request, handover_id, "handovers", session)


@router.get("/maintenance/{handover_id}/history", response_class=HTMLResponse)
async def maintenance_case_history(
    handover_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    redirect = _login_redirect(request)
    if redirect is not None:
        return redirect
    return await _history_response(request, handover_id, "maintenance", session)


async def _history_response(request: Request, handover_id, nav, session):
    _service, view = await _load_case(session, handover_id)
    handover = view.handover
    is_maintenance = (handover.kind or "handover") == CaseKind.MAINTENANCE.value
    expected_nav = "maintenance" if is_maintenance else "handovers"
    # A history page always lives under the case's own screen.
    if nav != expected_nav:
        base = "/maintenance" if is_maintenance else "/handovers"
        return _redirect308(f"{base}/{handover_id}/history")

    ctx = _common_ctx(request, f"History {handover.device_serial}", nav)
    ctx.update(
        handover=handover,
        timeline_groups=_build_timeline_groups(view.events),
        timeline_count=len(view.events),
    )
    return templates.TemplateResponse(request=request, name="case_history.html", context=ctx)


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
        return f"{actor_name} overrode the software check: {detail.get('reason', '')}"
    elif etype == "software_check_reevaluated":
        return "Software checks re-evaluated"
    elif etype == "recipient_identity_detected":
        return f"Recipient detected from device: {detail.get('username', '')}"
    elif etype == "recipient_identity_blocked":
        return "Recipient blocked: domain user not found"
    elif etype == "snipeit_recipient_confirmed":
        return f"{actor_name} confirmed the recipient in Snipe-IT"
    elif etype == "snipeit_checkout_performed":
        return "Checkout verified in Snipe-IT"
    elif etype == "document_uploaded":
        return "Signed paper scan attached"
    elif etype == "snipeit_document_pushed":
        return "Changes pushed to Snipe-IT"
    elif etype == "maintenance_updated":
        return f"Maintenance details updated: {', '.join(sorted(detail.keys()))}"
    elif etype == "handover_closed":
        return "Case closed with gaps"
    elif etype == "handover_reopened":
        return "Case reopened"
    elif etype == "handover_cancelled":
        return "Case cancelled"
    return etype.replace("_", " ").capitalize()


def _build_timeline_groups(events: list) -> list[dict]:
    if not events:
        return []
    sorted_events = sorted(
        events,
        key=lambda e: getattr(e, "created_at", getattr(e, "at", None)) or datetime.min,
        reverse=True,
    )
    entries: list[dict] = []
    for ev in sorted_events:
        dt = getattr(ev, "created_at", None)
        if dt is None:
            dt = getattr(ev, "at", None)
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt)
            except ValueError:
                dt = _now()
        elif dt is None:
            dt = _now()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        actor_raw = getattr(ev, "actor", "") or "System"
        actor_name = actor_raw.split("<")[0].strip() or actor_raw.split("@")[0] or "Engineer"
        detail = getattr(ev, "detail", {}) or {}
        sentence = _format_event_sentence(
            getattr(ev, "type", ""), detail, actor_name
        )
        entries.append(
            {
                "dt": dt,
                "date": dt.strftime("%d %b %Y"),
                "time": dt.strftime("%H:%M"),
                "actor": actor_name,
                "sentence": sentence,
            }
        )
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        groups.setdefault(entry["date"], []).append(entry)
    return [{"date": date, "entries": items} for date, items in groups.items()]


# -- old page URLs ------------------------------------------------------------
# Every old case URL answers 308 to its new home, keeping the query string.


@router.get("/new", response_class=HTMLResponse)
async def legacy_new_case(request: Request):
    return _redirect308("/handovers", _merge_query(request.url.query, "new=1"))


@router.get("/cases", response_class=HTMLResponse)
async def legacy_cases(request: Request, kind: str | None = None):
    if kind == "maintenance":
        return _redirect308("/maintenance", _without_kind(request.url.query))
    return _redirect308("/handovers", _without_kind(request.url.query))


def _merge_query(query: str, extra: str) -> str:
    if not query:
        return extra
    if extra in query:
        return query
    return f"{query}&{extra}"


def _without_kind(query: str) -> str:
    if not query:
        return ""
    parts = [
        p for p in query.split("&")
        if p and not p.startswith("kind=")
    ]
    return "&".join(parts)


@router.get("/cases/{handover_id}", response_class=HTMLResponse)
async def legacy_case(
    handover_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    kind = await _case_kind(session, handover_id)
    base = "/maintenance" if kind == CaseKind.MAINTENANCE.value else "/handovers"
    return _redirect308(f"{base}/{handover_id}", request.url.query)


@router.get("/cases/{handover_id}/history", response_class=HTMLResponse)
async def legacy_case_history(
    handover_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    kind = await _case_kind(session, handover_id)
    base = "/maintenance" if kind == CaseKind.MAINTENANCE.value else "/handovers"
    return _redirect308(f"{base}/{handover_id}/history", request.url.query)


async def _case_kind(session: AsyncSession, handover_id: uuid.UUID) -> str:
    from app.repositories.handovers import HandoverRepository

    try:
        handover = await HandoverRepository(session).get(handover_id)
        return handover.kind or CaseKind.HANDOVER.value
    except Exception:
        return CaseKind.HANDOVER.value


@router.get("/api/me")
async def me(
    request: Request,
    response: Response,
    user=Depends(current_user),
):
    token = get_or_create_token(request)
    response.headers["X-CSRF-Token"] = token
    return {"name": user.get("name"), "email": user.get("email"), "sso": config.SSO_ENABLED}
