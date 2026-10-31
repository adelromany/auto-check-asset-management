"""Handover API.

Routers stay thin: parse, authorize, call one service method, return a DTO.
Domain exceptions are translated to HTTP here and nowhere else.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import current_user, get_session
from app.domain.errors import (
    HandoverAlreadyExists,
    HandoverCancelled,
    HandoverCompleted,
    HandoverError,
    HandoverNotFound,
    InvalidStage,
    ManualStageRequired,
    StageNotRunnable,
)
from app.domain.stages import HandoverStatus
from app.dto.handover import (
    HandoverCreate,
    HandoverDetail,
    HandoverList,
    HandoverSummary,
)
from app.services.handovers import HandoverDetailView, HandoverService

router = APIRouter(prefix="/api/handovers", tags=["handovers"])

_CONFLICT_ERRORS = (
    HandoverAlreadyExists,
    HandoverCancelled,
    HandoverCompleted,
    ManualStageRequired,
    StageNotRunnable,
)


def _actor(user: dict) -> str:
    return user["email"]


def _detail(view: HandoverDetailView) -> HandoverDetail:
    return HandoverDetail.from_parts(
        view.handover,
        stages=view.stages,
        missing_steps=view.missing_steps,
        events=view.events,
    )


def _http_error(exc: HandoverError) -> HTTPException:
    if isinstance(exc, HandoverNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, InvalidStage):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, _CONFLICT_ERRORS):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post("", response_model=HandoverSummary, status_code=201)
async def create_handover(
    payload: HandoverCreate,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverSummary:
    service = HandoverService(session)
    try:
        handover = await service.create(
            device_serial=payload.device_serial,
            engineer_email=_actor(user),
            engineer_name=user.get("name") or "",
            ticket_ref=payload.ticket_ref,
        )
    except HandoverError as exc:
        raise _http_error(exc) from exc
    return HandoverSummary.model_validate(handover)


@router.get("", response_model=HandoverList)
async def list_handovers(
    status: HandoverStatus | None = Query(default=None),
    engineer: str | None = Query(default=None),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverList:
    service = HandoverService(session)
    items, total = await service.list(
        status=status.value if status is not None else None,
        engineer=engineer,
        created_from=created_from,
        created_to=created_to,
        page=page,
        page_size=page_size,
    )
    return HandoverList(
        items=[HandoverSummary.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{handover_id}", response_model=HandoverDetail)
async def get_handover(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverDetail:
    service = HandoverService(session)
    try:
        view = await service.get_detail(handover_id)
    except HandoverError as exc:
        raise _http_error(exc) from exc
    return _detail(view)


@router.post(
    "/{handover_id}/stages/{stage}/confirm", response_model=HandoverDetail
)
async def confirm_stage(
    handover_id: uuid.UUID,
    stage: str,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverDetail:
    service = HandoverService(session)
    try:
        view = await service.confirm_manual_stage(
            handover_id, stage, actor=_actor(user)
        )
    except HandoverError as exc:
        raise _http_error(exc) from exc
    return _detail(view)


@router.post("/{handover_id}/cancel", response_model=HandoverDetail)
async def cancel_handover(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverDetail:
    service = HandoverService(session)
    try:
        view = await service.cancel(handover_id, actor=_actor(user))
    except HandoverError as exc:
        raise _http_error(exc) from exc
    return _detail(view)
