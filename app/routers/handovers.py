"""Handover API.

Routers stay thin: parse, authorize, call one service method, return a DTO.
Domain exceptions are translated to HTTP here and nowhere else.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.snipeit import (
    SnipeItAuthError,
    SnipeItClient,
    SnipeItError,
    SnipeItNotFound,
    SnipeItRejected,
    SnipeItUnavailable,
)
from app.dependencies import current_user, get_session, get_snipeit_client
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
    CheckinRequest,
    CheckinResult,
    HandoverCreate,
    HandoverDetail,
    HandoverList,
    HandoverPreview,
    HandoverSummary,
    RecipientConfirm,
    RecipientSearchResult,
)
from app.services.handovers import HandoverDetailView, HandoverService
from app.services.snipeit_ops import SnipeItHandoverService

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


def _snipeit_http_error(exc: SnipeItError) -> HTTPException:
    """Translate client errors without ever exposing the token."""
    if isinstance(exc, SnipeItUnavailable):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, SnipeItAuthError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, SnipeItNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, SnipeItRejected):
        status = exc.status_code if exc.status_code < 500 else 502
        return HTTPException(status_code=status, detail=str(exc))
    return HTTPException(status_code=502, detail="Snipe-IT request failed.")


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


# -- Phase 5: Snipe-IT write operations -------------------------------------


@router.post(
    "/{handover_id}/recipient/search",
    response_model=RecipientSearchResult,
)
async def search_recipient(
    handover_id: uuid.UUID,
    q: str = Query(min_length=1, max_length=200),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> RecipientSearchResult:
    service = SnipeItHandoverService(session)
    try:
        return await service.search_recipients(
            handover_id,
            q,
            client=client,
            engineer_email=_actor(user),
            engineer_name=user.get("name") or "",
        )
    except HandoverError as exc:
        raise _http_error(exc) from exc
    except SnipeItError as exc:
        raise _snipeit_http_error(exc) from exc


@router.post(
    "/{handover_id}/recipient/confirm",
    response_model=HandoverDetail,
)
async def confirm_recipient(
    handover_id: uuid.UUID,
    payload: RecipientConfirm,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverDetail:
    service = SnipeItHandoverService(session)
    try:
        view = await service.confirm_recipient(
            handover_id,
            snipeit_user_id=payload.snipeit_user_id,
            not_found=payload.not_found,
            actor=_actor(user),
            client=client,
        )
    except HandoverError as exc:
        raise _http_error(exc) from exc
    except SnipeItError as exc:
        raise _snipeit_http_error(exc) from exc
    return _detail(view)


@router.get("/{handover_id}/preview", response_model=HandoverPreview)
async def preview_handover(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverPreview:
    service = SnipeItHandoverService(session)
    try:
        return await service.preview(handover_id, client=client)
    except HandoverError as exc:
        raise _http_error(exc) from exc
    except SnipeItError as exc:
        raise _snipeit_http_error(exc) from exc


@router.post("/{handover_id}/checkin", response_model=CheckinResult)
async def checkin_assets(
    handover_id: uuid.UUID,
    payload: CheckinRequest,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> CheckinResult:
    service = SnipeItHandoverService(session)
    try:
        outcomes = await service.checkin_assets(
            handover_id,
            payload.asset_ids,
            actor=_actor(user),
            client=client,
        )
    except HandoverError as exc:
        raise _http_error(exc) from exc
    except SnipeItError as exc:
        raise _snipeit_http_error(exc) from exc
    return CheckinResult(handover_id=handover_id, results=outcomes)


@router.post("/{handover_id}/checkout", response_model=HandoverDetail)
async def checkout_handover(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverDetail:
    service = SnipeItHandoverService(session)
    try:
        view = await service.checkout(
            handover_id, actor=_actor(user), client=client
        )
    except HandoverError as exc:
        raise _http_error(exc) from exc
    except SnipeItError as exc:
        raise _snipeit_http_error(exc) from exc
    return _detail(view)
