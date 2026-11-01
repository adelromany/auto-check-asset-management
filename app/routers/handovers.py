"""Handover API.

Routers stay thin: parse, authorize, call one service method, return a DTO.
Domain exceptions are translated to HTTP here and nowhere else.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.clients.snipeit import SnipeItClient, SnipeItError
from app.dependencies import current_user, get_session, get_snipeit_client
from app.domain.errors import HandoverError
from app.domain.stages import HandoverStatus
from app.dto.handover import (
    CheckinRequest,
    CheckinResult,
    HandoverCreate,
    HandoverDetail,
    HandoverList,
    HandoverPreview,
    HandoverPrintRequest,
    HandoverPrintState,
    HandoverSummary,
    ManualPrintConfirmation,
    RecipientConfirm,
    RecipientSearchResult,
    SoftwareCheckOverride,
)
from app.routers.http_errors import (
    handover_detail,
    handover_http_error,
    snipeit_http_error,
)
from app.services import handover_printing
from app.services.handovers import HandoverService
from app.services.snipeit_ops import SnipeItHandoverService
from app.services.software_check import SoftwareCheckService

router = APIRouter(prefix="/api/handovers", tags=["handovers"])

def _actor(user: dict) -> str:
    return user["email"]


def _checkout_passed(view) -> bool:
    """True when the checkout stage of this view is passed (or skipped)."""
    for stage in view.stages:
        if stage.stage == "checkout":
            return stage.status in ("passed", "skipped")
    return False


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
        raise handover_http_error(exc) from exc
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
        raise handover_http_error(exc) from exc
    return handover_detail(view)


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
        raise handover_http_error(exc) from exc
    return handover_detail(view)


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
        raise handover_http_error(exc) from exc
    return handover_detail(view)


# -- Phase 5: Snipe-IT write operations -------------------------------------


@router.post(
    "/{handover_id}/recipient/search",
    response_model=RecipientSearchResult,
)
async def search_recipient(
    handover_id: uuid.UUID,
    q: str | None = Query(default=None, max_length=200),
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
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeithandover_http_error(exc) from exc


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
            acknowledge_same_as_engineer=payload.acknowledge_same_as_engineer,
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeithandover_http_error(exc) from exc
    return handover_detail(view)


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
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeithandover_http_error(exc) from exc


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
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeithandover_http_error(exc) from exc
    return CheckinResult(handover_id=handover_id, results=outcomes)


@router.post("/{handover_id}/checkout", response_model=HandoverDetail)
async def checkout_handover(
    handover_id: uuid.UUID,
    background: BackgroundTasks,
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
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeithandover_http_error(exc) from exc
    # The portal prints the handover form itself after a successful checkout,
    # in a background task with its own database session. A print failure
    # never undoes the checkout: it only fails the report_printed stage.
    if config.AUTO_PRINT_AFTER_CHECKOUT and _checkout_passed(view):
        # Starlette runs background tasks before the request-scoped session is
        # committed (dependency teardown comes last), so without this commit
        # the print would read a database where the checkout never happened
        # and silently skip itself. Committing here makes the checkout visible
        # to the print's own session; the teardown commit is then a no-op.
        await session.commit()
        background.add_task(
            handover_printing.auto_print_after_checkout,
            handover_id,
            actor=_actor(user),
        )
    return handover_detail(view)


@router.post(
    "/{handover_id}/software-check/override",
    response_model=HandoverDetail,
)
async def override_software_check(
    handover_id: uuid.UUID,
    payload: SoftwareCheckOverride,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverDetail:
    service = SoftwareCheckService(session)
    try:
        view = await service.override(
            handover_id, reason=payload.reason, actor=_actor(user)
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


@router.post(
    "/{handover_id}/software-check/reevaluate",
    response_model=HandoverDetail,
)
async def reevaluate_software_check(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverDetail:
    service = SoftwareCheckService(session)
    try:
        view = await service.reevaluate(
            handover_id, actor=_actor(user)
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


# -- Phase 7: the portal prints the handover form ---------------------------


@router.get("/{handover_id}/print", response_model=HandoverPrintState)
async def get_print_state(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
) -> HandoverPrintState:
    """State of the print: idle, running, accepted, failed or pdf_ready."""
    service = handover_printing.HandoverPrintService()
    try:
        view = await service.state(handover_id)
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return HandoverPrintState.from_view(view)


@router.post("/{handover_id}/print", response_model=HandoverPrintState)
async def start_print(
    handover_id: uuid.UUID,
    background: BackgroundTasks,
    payload: HandoverPrintRequest | None = None,
    user: dict = Depends(current_user),
) -> HandoverPrintState:
    """Start (or retry) the print. ``{"reprint": true}`` starts a new attempt."""
    service = handover_printing.HandoverPrintService()
    reprint = bool(payload.reprint) if payload is not None else False
    try:
        view = await service.start(
            handover_id, actor=_actor(user), reprint=reprint
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    if view.attempt_id is not None:
        background.add_task(service.run, handover_id, view.attempt_id)
    return HandoverPrintState.from_view(view)


@router.post("/{handover_id}/print/confirm", response_model=HandoverDetail)
async def confirm_print_manually(
    handover_id: uuid.UUID,
    payload: ManualPrintConfirmation,
    user: dict = Depends(current_user),
) -> HandoverDetail:
    """pdf_only servers only: the engineer states why there is no printer."""
    service = handover_printing.HandoverPrintService()
    try:
        view = await service.confirm_manually(
            handover_id, actor=_actor(user), reason=payload.reason
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


@router.get("/{handover_id}/print/pdf")
async def download_printed_form(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
) -> FileResponse:
    """The stored PDF of the last attempt (path from the database only)."""
    service = handover_printing.HandoverPrintService()
    try:
        path, download_name = await service.pdf_path(handover_id)
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=download_name,
        headers={"Cache-Control": "no-store"},
    )
