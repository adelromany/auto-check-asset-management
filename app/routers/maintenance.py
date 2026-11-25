"""Maintenance API (Phase 06)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.snipeit import SnipeItClient
from app.dependencies import current_user, get_session, get_snipeit_client
from app.domain.errors import HandoverError
from app.dto.dashboard import MaintenanceCaseOut
from app.dto.handover import HandoverDetail
from app.dto.maintenance import (
    MaintenanceBatchReceive,
    MaintenanceBatchResult,
    MaintenanceBatchSend,
    MaintenanceCaseCreate,
    MaintenanceDeviceLookup,
    MaintenanceReason,
    MaintenanceVendor,
    MaintenanceVendorCreate,
    MaintenanceVendorUpdate,
)
from app.repositories.maintenance import MaintenanceRepository
from app.routers.http_errors import handover_detail, handover_http_error
from app.services.maintenance import MaintenanceService

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


@router.get("/device-lookup", response_model=MaintenanceDeviceLookup)
async def lookup_device(
    serial: str = Query(min_length=1, max_length=100),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> MaintenanceDeviceLookup:
    try:
        return await MaintenanceService(session).lookup_device(serial, client=client)
    except HandoverError as exc:
        raise handover_http_error(exc) from exc


@router.get("/cases", response_model=list[MaintenanceCaseOut])
async def list_cases(
    state: str | None = Query(default=None, pattern="^(with_it|at_vendor|returned)$"),
    company: str | None = Query(default=None, max_length=120),
    model: str | None = Query(default=None, max_length=120),
    vendor_id: int | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MaintenanceCaseOut]:
    return await MaintenanceService(session).list_cases(
        state=state, company=company, model=model, vendor_id=vendor_id, q=q
    )


@router.post("/cases", response_model=HandoverDetail, status_code=201)
async def create_case(
    payload: MaintenanceCaseCreate,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverDetail:
    try:
        view = await MaintenanceService(session).create_case(
            serial=payload.serial,
            reason_id=payload.reason_id,
            reason_text=payload.reason_text,
            planned_vendor_id=payload.planned_vendor_id,
            engineer_email=user["email"],
            engineer_name=user.get("name") or "",
            client=client,
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


@router.post("/cases/{case_id}/set-status", response_model=HandoverDetail)
async def set_status(
    case_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverDetail:
    try:
        view = await MaintenanceService(session).set_status(
            case_id, engineer_email=user["email"], client=client
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


@router.post("/cases/{case_id}/take-back", response_model=HandoverDetail)
async def take_back(
    case_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverDetail:
    try:
        view = await MaintenanceService(session).take_back(
            case_id, engineer_email=user["email"], client=client
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


@router.post("/batches/send", response_model=list[MaintenanceBatchResult])
async def batch_send(
    payload: MaintenanceBatchSend,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MaintenanceBatchResult]:
    try:
        return await MaintenanceService(session).batch_send(
            payload.case_ids,
            vendor_id=payload.vendor_id,
            sent_date=payload.sent_date,
            engineer_email=user["email"],
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc


@router.post("/batches/receive", response_model=list[MaintenanceBatchResult])
async def batch_receive(
    payload: MaintenanceBatchReceive,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> list[MaintenanceBatchResult]:
    try:
        return await MaintenanceService(session).batch_receive(
            payload.case_ids,
            returned_date=payload.returned_date,
            engineer_email=user["email"],
            client=client,
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc


@router.post("/cases/{case_id}/ready-status", response_model=HandoverDetail)
async def ready_status(
    case_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverDetail:
    try:
        view = await MaintenanceService(session).ready_status(
            case_id, engineer_email=user["email"], client=client
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return handover_detail(view)


@router.get("/vendors", response_model=list[MaintenanceVendor])
async def list_vendors(
    include_inactive: bool = Query(default=False),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MaintenanceVendor]:
    repo = MaintenanceRepository(session)
    vendors = await repo.list_vendors(include_inactive=include_inactive)
    stats = await repo.vendor_stats()
    return [
        MaintenanceVendor.model_validate(vendor).model_copy(
            update=stats.get(vendor.id, {})
        )
        for vendor in vendors
    ]


@router.post("/vendors", response_model=MaintenanceVendor, status_code=201)
async def create_vendor(
    payload: MaintenanceVendorCreate,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MaintenanceVendor:
    repo = MaintenanceRepository(session)
    if await repo.find_vendor(payload.name):
        existing = await repo.find_vendor(payload.name)
        raise HTTPException(
            status_code=409,
            detail={"message": "Vendor already exists", "id": existing.id},
        )
    try:
        vendor = await repo.create_vendor(payload.model_dump())
    except IntegrityError as exc:
        await session.rollback()
        existing = await repo.find_vendor(payload.name)
        raise HTTPException(
            status_code=409,
            detail={"message": "Vendor already exists", "id": existing.id if existing else None},
        ) from exc
    return MaintenanceVendor.model_validate(vendor)


@router.patch("/vendors/{vendor_id}", response_model=MaintenanceVendor)
async def update_vendor(
    vendor_id: int,
    payload: MaintenanceVendorUpdate,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MaintenanceVendor:
    repo = MaintenanceRepository(session)
    vendor = await repo.get_vendor(vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    values = payload.model_dump(exclude_unset=True)
    if "name" in values:
        duplicate = await repo.find_vendor(values["name"])
        if duplicate and duplicate.id != vendor.id:
            raise HTTPException(status_code=409, detail={"message": "Vendor already exists", "id": duplicate.id})
    await repo.update_vendor(vendor, values)
    return MaintenanceVendor.model_validate(vendor)


@router.delete("/vendors/{vendor_id}", status_code=204)
async def delete_vendor(
    vendor_id: int,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    repo = MaintenanceRepository(session)
    vendor = await repo.get_vendor(vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    if await repo.vendor_is_referenced(vendor_id):
        raise HTTPException(status_code=409, detail="Vendor has devices. Deactivate instead")
    await repo.delete_vendor(vendor)


@router.get("/reasons", response_model=list[MaintenanceReason])
async def list_reasons(
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MaintenanceReason]:
    repository = MaintenanceRepository(session)
    await repository.seed_defaults()
    categories = await repository.list_diagnosis_categories()
    return [MaintenanceReason.model_validate(category) for category in categories]
