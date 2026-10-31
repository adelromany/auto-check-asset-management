"""Operations dashboard API (Phase 7).

Two reads: the aggregate summary that feeds the KPI tiles and the paged rows
that feed the handover table. Both accept the same ``from``/``to`` window.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import current_user, get_session
from app.dto.dashboard import DashboardSummaryOut, HandoverRowListOut
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/handovers/summary", response_model=DashboardSummaryOut)
async def handovers_summary(
    created_from: str | None = Query(default=None, alias="from"),
    created_to: str | None = Query(default=None, alias="to"),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> DashboardSummaryOut:
    service = DashboardService(session)
    return await service.summary(
        created_from=_parse_bound(created_from, end_of_day=False),
        created_to=_parse_bound(created_to, end_of_day=True),
    )


@router.get("/handovers", response_model=HandoverRowListOut)
async def handover_rows(
    status: str | None = Query(default=None),
    engineer: str | None = Query(default=None),
    created_from: str | None = Query(default=None, alias="from"),
    created_to: str | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverRowListOut:
    service = DashboardService(session)
    return await service.rows(
        status=status,
        engineer=engineer,
        created_from=_parse_bound(created_from, end_of_day=False),
        created_to=_parse_bound(created_to, end_of_day=True),
        page=page,
        page_size=page_size,
    )


def _parse_bound(value: str | None, *, end_of_day: bool) -> datetime | None:
    """Accept an ISO date or datetime; a date-only ``to`` includes that day."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid ISO date: {value}"
        ) from exc
    if len(text) == 10 and end_of_day:
        parsed = parsed + timedelta(days=1, microseconds=-1)
    return parsed
