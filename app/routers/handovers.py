"""Handover API.

Routers stay thin: parse, authorize, call one service method, return a DTO.
Domain exceptions are translated to HTTP here and nowhere else.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.clients.snipeit import SnipeItClient, SnipeItError
from app.dependencies import current_user, get_session, get_snipeit_client
from app.domain.errors import HandoverError
from app.domain.stages import HandoverStatus
from app.dto.handover import (
    AgentReportAttach,
    CategoryOut,
    CheckinRequest,
    CheckinResult,
    CheckoutRequest,
    CloseCaseRequest,
    DestinationOut,
    DeviceStatusRequest,
    HandoverCreate,
    HandoverDetail,
    HandoverList,
    HandoverPreview,
    HandoverSummary,
    MaintenanceUpdate,
    ModeRequest,
    NotDoneRequest,
    RecipientConfirm,
    RecipientItemOut,
    RecipientSearchResult,
    RecipientSelectionRequest,
    SoftwareCheckOverride,
)
from app.repositories.maintenance import MaintenanceRepository
from app.routers.http_errors import (
    handover_detail,
    handover_http_error,
    snipeit_http_error,
)
from app.schemas import AgentPayload
from app.services.documents import DocumentService
from app.services.handovers import HandoverService
from app.services.snipeit_ops import SnipeItHandoverService
from app.services.software_check import SoftwareCheckService

router = APIRouter(prefix="/api/handovers", tags=["handovers"])

def _actor(user: dict) -> str:
    return user["email"]


@router.post("", response_model=HandoverSummary, status_code=201)
async def create_handover(
    payload: HandoverCreate,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverSummary:
    service = HandoverService(session)
    try:
        handover = await service.create(
            device_serial=payload.device_serial,
            engineer_email=_actor(user),
            engineer_name=user.get("name") or "",
            ticket_ref=payload.ticket_ref,
            kind=payload.kind,
            mode=payload.mode,
            client=client,
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return HandoverSummary.model_validate(handover)


@router.get("", response_model=HandoverList)
async def list_handovers(
    status: HandoverStatus | None = Query(default=None),
    engineer: str | None = Query(default=None),
    kind: str | None = Query(default=None, pattern="^(handover|maintenance)$"),
    outcome: str | None = Query(default=None, pattern="^(complete|not_complete|ready)$"),
    company: str | None = Query(default=None, max_length=100),
    q: str | None = Query(default=None, max_length=100),
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
        kind=kind,
        outcome=outcome,
        company=company,
        q=q,
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


@router.get("/active", response_model=HandoverSummary | None)
async def active_case(
    serial: str = Query(min_length=1, max_length=100),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverSummary | None:
    """The active case for a serial, or null. Additive lookup for `/new`."""
    service = HandoverService(session)
    handover = await service.find_active_by_serial(serial)
    return HandoverSummary.model_validate(handover) if handover else None


@router.get("/maintenance/destinations", response_model=list[DestinationOut])
@router.get("/maintenance/vendors", response_model=list[DestinationOut])
async def list_maintenance_vendors(
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[DestinationOut]:
    repo = MaintenanceRepository(session)
    destinations = await repo.list_destinations()
    return [DestinationOut.model_validate(d) for d in destinations]


@router.get("/maintenance/categories", response_model=list[CategoryOut])
async def list_diagnosis_categories(
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[CategoryOut]:
    repo = MaintenanceRepository(session)
    categories = await repo.list_diagnosis_categories()
    return [CategoryOut.model_validate(c) for c in categories]


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
@router.post(
    "/{handover_id}/operations/{stage}/confirm", response_model=HandoverDetail
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


@router.get("/{handover_id}/device-live")
async def get_device_live(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> dict:
    try:
        return await SnipeItHandoverService(session).device_live(
            handover_id, client=client, actor=_actor(user)
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeit_http_error(exc) from exc


@router.post("/{handover_id}/device/checkin")
async def checkin_device(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> dict:
    try:
        return await SnipeItHandoverService(session).checkin_device(
            handover_id, actor=_actor(user), client=client
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeit_http_error(exc) from exc


@router.post("/{handover_id}/mode", response_model=HandoverDetail)
async def change_handover_mode(
    handover_id: uuid.UUID,
    payload: ModeRequest,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverDetail:
    service = HandoverService(session)
    try:
        view = await service.change_mode(
            handover_id, mode=payload.mode, actor=_actor(user)
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


@router.post("/pending-user/check-all")
async def check_all_pending_users(
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
):
    from app.services.pending_users import check_pending_users
    views = await check_pending_users(session, client)
    return {"checked": len(views)}


@router.post("/{handover_id}/pending-user/check", response_model=HandoverDetail)
async def check_one_pending_user(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
):
    from app.services.pending_users import check_pending_user
    try:
        view = await check_pending_user(session, handover_id, actor=_actor(user), client=client)
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


@router.delete("/{handover_id}", status_code=204)
async def delete_handover(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        await HandoverService(session).delete(handover_id, actor=_actor(user))
    except HandoverError as exc:
        raise handover_http_error(exc) from exc


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


@router.post("/{handover_id}/operations/{operation}/not-done", response_model=HandoverDetail)
async def mark_operation_not_done(
    handover_id: uuid.UUID,
    operation: str,
    payload: NotDoneRequest,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverDetail:
    service = HandoverService(session)
    try:
        view = await service.mark_not_done(
            handover_id, operation, reason=payload.reason, actor=_actor(user)
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


@router.post("/{handover_id}/operations/{operation}/retry", response_model=HandoverDetail)
async def retry_operation(
    handover_id: uuid.UUID,
    operation: str,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverDetail:
    service = HandoverService(session)
    try:
        if operation == "document_pushed":
            view = await DocumentService(
                session,
                documents_dir=config.DOCUMENTS_DIR,
                max_bytes=config.DOCUMENT_MAX_BYTES,
            ).push(
                handover_id,
                actor=_actor(user),
                client=client,
                require_linked_asset=True,
            )
        else:
            view = await service.retry_operation(
                handover_id, operation, actor=_actor(user)
            )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeit_http_error(exc) from exc
    return handover_detail(view)


@router.post("/{handover_id}/close", response_model=HandoverDetail)
async def close_case_with_gaps(
    handover_id: uuid.UUID,
    payload: CloseCaseRequest,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverDetail:
    service = HandoverService(session)
    try:
        view = await service.close_with_gaps(
            handover_id, confirmation=payload.confirmation, actor=_actor(user)
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


@router.post("/{handover_id}/reopen", response_model=HandoverDetail)
async def reopen_case(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverDetail:
    service = HandoverService(session)
    try:
        view = await service.reopen(handover_id, actor=_actor(user))
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


@router.post("/{handover_id}/maintenance", response_model=HandoverDetail)
async def update_maintenance(
    handover_id: uuid.UUID,
    payload: MaintenanceUpdate,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverDetail:
    service = HandoverService(session)
    try:
        view = await service.update_maintenance_info(
            handover_id,
            payload.model_dump(exclude_unset=True),
            actor=_actor(user),
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


# -- Phase 5: Snipe-IT write operations -------------------------------------


@router.post("/{handover_id}/recipient", response_model=HandoverDetail)
async def choose_recipient(
    handover_id: uuid.UUID,
    payload: RecipientSelectionRequest,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverDetail | JSONResponse:
    """Choose a Snipe-IT recipient, no recipient, or a free-form recipient."""
    service = SnipeItHandoverService(session)
    try:
        if payload.mode == "pending_user":
            from app.services.pending_users import register_pending
            view = await register_pending(
                session, handover_id, employee_code=payload.employee_code,
                username=payload.username, name=payload.name,
                actor=_actor(user), client=client,
            )
            return handover_detail(view)
        view = await service.choose_recipient(
            handover_id,
            mode=payload.mode,
            user_id=payload.user_id,
            name=payload.name,
            email=payload.email,
            actor=_actor(user),
            client=client,
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeit_http_error(exc) from exc
    return handover_detail(view)


@router.get(
    "/{handover_id}/recipient/items",
    response_model=list[RecipientItemOut],
)
async def list_recipient_items(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> list[RecipientItemOut]:
    service = SnipeItHandoverService(session)
    try:
        items = await service.list_recipient_items(handover_id, client=client)
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeit_http_error(exc) from exc
    return [RecipientItemOut.model_validate(item) for item in items]


@router.post(
    "/{handover_id}/recipient/items/checkin",
    response_model=CheckinResult,
)
async def checkin_recipient_items(
    handover_id: uuid.UUID,
    payload: CheckinRequest,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> CheckinResult:
    service = SnipeItHandoverService(session)
    try:
        outcomes = await service.checkin_recipient_items(
            handover_id,
            payload.asset_ids,
            actor=_actor(user),
            client=client,
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeit_http_error(exc) from exc
    return CheckinResult(handover_id=handover_id, results=outcomes)


@router.post(
    "/{handover_id}/recipient/items/confirm",
    response_model=HandoverDetail,
)
async def confirm_recipient_items(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverDetail:
    service = SnipeItHandoverService(session)
    try:
        view = await service.confirm_recipient_items(
            handover_id, actor=_actor(user), client=client
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeit_http_error(exc) from exc
    return handover_detail(view)


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
        raise snipeit_http_error(exc) from exc


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
        raise snipeit_http_error(exc) from exc
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
        raise snipeit_http_error(exc) from exc


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
        raise snipeit_http_error(exc) from exc
    return CheckinResult(handover_id=handover_id, results=outcomes)


@router.post("/{handover_id}/checkout", response_model=HandoverDetail)
async def checkout_handover(
    handover_id: uuid.UUID,
    payload: CheckoutRequest | None = None,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverDetail:
    service = SnipeItHandoverService(session)
    try:
        view = await service.checkout(
            handover_id,
            actor=_actor(user),
            client=client,
            replace_holder=bool(payload and payload.replace_holder),
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeit_http_error(exc) from exc
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


@router.post("/{handover_id}/maintenance/status-label")
async def maintenance_status_label(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> dict:
    """Update the Snipe-IT status label for the device's maintenance state.

    Never raises for "not configured" / "no asset": the UI shows the note and
    records the snipeit_status operation as not done instead.
    """
    service = SnipeItHandoverService(session)
    return await service.update_maintenance_status(
        handover_id, actor=_actor(user), client=client
    )


@router.post("/{handover_id}/device-status", response_model=HandoverDetail)
async def set_device_status(
    handover_id: uuid.UUID,
    payload: DeviceStatusRequest,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverDetail:
    """Set the device's Snipe-IT status and record the device-status part."""
    service = SnipeItHandoverService(session)
    try:
        view = await service.set_device_status(
            handover_id,
            status_label_id=payload.status_label_id,
            actor=_actor(user),
            client=client,
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


@router.post("/{handover_id}/attach-report", response_model=HandoverDetail)
async def attach_agent_report(
    handover_id: uuid.UUID,
    payload: AgentReportAttach,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HandoverDetail:
    """Record an agent report collected through the sync flow on this case.

    Same path as the code-based agent submit; the report arrives from the
    engineer's signed-in session instead of the device's one-liner.
    """
    service = HandoverService(session)
    try:
        handover = await service.record_agent_report(
            handover_id,
            AgentPayload(**payload.payload).model_dump(),
            actor=_actor(user),
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    view = await service.get_detail(handover_id)
    return handover_detail(view)
