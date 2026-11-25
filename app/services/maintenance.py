"""Maintenance case orchestration (Phase 06).

The service owns Snipe-IT reads and maintenance operation transitions. Routers
only parse requests and translate errors.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.snipeit import SnipeItClient, SnipeItError, SnipeItNotFound
from app.domain.catalog import Operation
from app.domain.errors import (
    DeviceNotInSnipeIt,
    HandoverAlreadyExists,
    MaintenanceCaseExists,
    MaintenanceReasonInvalid,
    SnipeItUnreachable,
)
from app.domain.stages import StageStatus
from app.dto.maintenance import MaintenanceDeviceLookup
from app.repositories.maintenance import MaintenanceRepository
from app.services.handovers import HandoverDetailView, HandoverService


class MaintenanceService:
    """Phase 06 maintenance use cases."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._core = HandoverService(session)
        self._repository = MaintenanceRepository(session)

    async def lookup_device(
        self, serial: str, *, client: SnipeItClient
    ) -> MaintenanceDeviceLookup:
        cleaned = serial.strip()
        if not cleaned:
            raise MaintenanceReasonInvalid("Serial is required.")
        try:
            asset = await client.get_asset_by_exact_serial(cleaned)
        except SnipeItNotFound as exc:
            raise DeviceNotInSnipeIt() from exc
        except SnipeItError as exc:
            raise SnipeItUnreachable() from exc
        return MaintenanceDeviceLookup(
            asset_id=asset.id,
            asset_tag=asset.asset_tag,
            serial=asset.serial or cleaned,
            model=asset.model,
            company=asset.company,
            status=asset.status,
            assigned_to=asset.assigned_to_name,
        )

    async def create_case(
        self,
        *,
        serial: str,
        reason_id: int | None,
        reason_text: str | None,
        planned_vendor_id: int | None,
        engineer_email: str,
        engineer_name: str,
        client: SnipeItClient,
    ) -> HandoverDetailView:
        cleaned_serial = serial.strip()
        existing = await self._core.find_active_by_serial(cleaned_serial)
        if existing is not None:
            raise MaintenanceCaseExists(str(existing.id))

        reason = None
        reason_name = ""
        if reason_id is not None:
            reason = await self._repository.get_diagnosis_category(reason_id)
            if reason is None:
                raise MaintenanceReasonInvalid("Reason was not found.")
            reason_name = reason.name
        cleaned_text = (reason_text or "").strip()
        if reason is not None and reason.name.casefold() == "other" and not cleaned_text:
            raise MaintenanceReasonInvalid("Details are required for Other.")
        if len(cleaned_text) > 300:
            raise MaintenanceReasonInvalid("Details must be 300 characters or fewer.")

        vendor = None
        if planned_vendor_id is not None:
            vendor = await self._repository.get_destination(planned_vendor_id)
            if vendor is None:
                raise MaintenanceReasonInvalid("Vendor was not found.")

        try:
            handover = await self._core.create(
                device_serial=cleaned_serial,
                engineer_email=engineer_email,
                engineer_name=engineer_name,
                kind="maintenance",
                client=client,
                exact_serial=True,
            )
        except HandoverAlreadyExists as exc:
            existing = await self._core.find_active_by_serial(cleaned_serial)
            if existing is not None:
                raise MaintenanceCaseExists(str(existing.id)) from exc
            raise

        assert handover.maintenance is not None
        handover.maintenance.received_date = date.today()
        if reason_name:
            handover.maintenance.diagnosis_category = reason_name
        if cleaned_text:
            handover.maintenance.reason_text = cleaned_text
        if vendor is not None:
            handover.maintenance.destination_id = vendor.id
            handover.maintenance.destination = vendor
        await self._session.flush()

        assignee = None
        if handover.snipeit_asset_id is not None:
            try:
                asset = await client.get_asset(handover.snipeit_asset_id)
                assignee = asset.assigned_to_name
            except SnipeItError:
                assignee = None

        view = await self._core.record_operation(
            handover.id,
            Operation.RECEIVED,
            status=StageStatus.PASSED,
            reason=None,
            detail={"assigned_to_name": assignee},
            actor=engineer_email,
            input_checks=False,
        )
        if reason_name:
            view = await self._core.record_operation(
                handover.id,
                Operation.DIAGNOSIS,
                status=StageStatus.PASSED,
                reason=None,
                detail={"reason_id": reason_id, "reason": reason_name},
                actor=engineer_email,
                input_checks=False,
            )
        return view
