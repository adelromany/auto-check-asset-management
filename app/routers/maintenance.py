"""Maintenance API (Phase 06)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.snipeit import SnipeItClient
from app.dependencies import current_user, get_session, get_snipeit_client
from app.domain.errors import HandoverError
from app.dto.handover import HandoverDetail
from app.dto.maintenance import (
    MaintenanceCaseCreate,
    MaintenanceDeviceLookup,
    MaintenanceReason,
    MaintenanceVendor,
    MaintenanceVendorCreate,
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


@router.get("/vendors", response_model=list[MaintenanceVendor])
async def list_vendors(
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MaintenanceVendor]:
    vendors = await MaintenanceRepository(session).list_vendors()
    return [MaintenanceReason.model_validate(vendor) for vendor in vendors]


@router.post("/vendors", response_model=MaintenanceVendor, status_code=201)
async def create_vendor(
    payload: MaintenanceVendorCreate,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MaintenanceVendor:
    vendor = await MaintenanceRepository(session).ensure_vendor(payload.name)
    await session.flush()
    return MaintenanceVendor.model_validate(vendor)


@router.get("/reasons", response_model=list[MaintenanceReason])
async def list_reasons(
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MaintenanceReason]:
    repository = MaintenanceRepository(session)
    await repository.seed_defaults()
    categories = await repository.list_diagnosis_categories()
    return [MaintenanceReason.model_validate(category) for category in categories]
