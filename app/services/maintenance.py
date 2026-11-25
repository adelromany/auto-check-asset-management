"""Maintenance case orchestration (Phase 06).

The service owns Snipe-IT reads and maintenance operation transitions. Routers
only parse requests and translate errors.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.clients.snipeit import SnipeItClient, SnipeItError, SnipeItNotFound
from app.db.models.maintenance import MaintenanceInfo
from app.domain.catalog import Operation
from app.domain.errors import (
    CaseStateConflict,
    DeviceNotInSnipeIt,
    HandoverAlreadyExists,
    HandoverError,
    MaintenanceCaseExists,
    MaintenanceLabelNotFound,
    MaintenanceReasonInvalid,
    SnipeItUnreachable,
)
from app.domain.maintenance_rules import (
    MaintenanceState,
    days_in_maintenance,
    derive_maintenance_state,
)
from app.domain.stages import StageStatus
from app.dto.dashboard import MaintenanceCaseOut
from app.dto.maintenance import (
    MaintenanceBatchResult,
    MaintenanceDeviceLookup,
)
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
        except (HandoverAlreadyExists, IntegrityError) as exc:
            await self._session.rollback()
            existing = await self._core.find_active_by_serial(cleaned_serial)
            if existing is not None:
                raise MaintenanceCaseExists(str(existing.id)) from exc
            if isinstance(exc, IntegrityError):
                raise MaintenanceCaseExists("") from exc
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
        handover.recipient_snipeit_name = assignee

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

    async def set_status(
        self,
        case_id: uuid.UUID,
        *,
        engineer_email: str,
        client: SnipeItClient,
    ) -> HandoverDetailView:
        """Set and verify the Snipe-IT Maintenance status label."""
        handover = await self._core.get(case_id, with_details=True)
        if handover.snipeit_asset_id is None:
            raise MaintenanceReasonInvalid("The case has no Snipe-IT device.")
        label = config.SNIPEIT_STATUS_MAINTENANCE
        try:
            label_id = await client.find_status_label_id(label)
        except SnipeItError as exc:
            return await self._core.record_operation(
                case_id,
                Operation.SNIPEIT_STATUS,
                status=StageStatus.FAILED,
                reason=str(exc),
                detail={"label": label},
                actor=engineer_email,
                input_checks=False,
            )
        if label_id is None:
            raise MaintenanceLabelNotFound(label)
        try:
            result = await client.update_asset_status(handover.snipeit_asset_id, label_id)
            asset = await client.get_asset(handover.snipeit_asset_id)
        except SnipeItError as exc:
            return await self._core.record_operation(
                case_id,
                Operation.SNIPEIT_STATUS,
                status=StageStatus.FAILED,
                reason=str(exc),
                detail={"label": label},
                actor=engineer_email,
                input_checks=False,
            )
        matched = str(asset.status or "").strip().casefold() == label.strip().casefold()
        if matched and result.status == "success":
            handover.snipeit_status_name = asset.status
            await self._session.flush()
            return await self._core.record_operation(
                case_id,
                Operation.SNIPEIT_STATUS,
                status=StageStatus.PASSED,
                reason=None,
                detail={"label": label, "status": asset.status},
                actor=engineer_email,
                input_checks=False,
            )
        reason = f"Status is {asset.status}"
        return await self._core.record_operation(
            case_id,
            Operation.SNIPEIT_STATUS,
            status=StageStatus.FAILED,
            reason=reason,
            detail={"label": label, "status": asset.status},
            actor=engineer_email,
            input_checks=False,
        )

    async def take_back(
        self,
        case_id: uuid.UUID,
        *,
        engineer_email: str,
        client: SnipeItClient,
    ) -> HandoverDetailView:
        """Check in an assigned device, or record not done when unassigned."""
        handover = await self._core.get(case_id, with_details=True)
        if handover.snipeit_asset_id is None:
            raise MaintenanceReasonInvalid("The case has no Snipe-IT device.")
        try:
            asset = await client.get_asset(handover.snipeit_asset_id)
        except SnipeItError as exc:
            return await self._core.record_operation(
                case_id,
                Operation.TAKEN_BACK,
                status=StageStatus.FAILED,
                reason=str(exc),
                detail={},
                actor=engineer_email,
                input_checks=False,
            )
        if asset.assigned_to_id is None:
            handover.recipient_snipeit_name = None
            await self._session.flush()
            return await self._core.record_operation(
                case_id,
                Operation.TAKEN_BACK,
                status=StageStatus.NOT_DONE,
                reason="Not assigned",
                detail={},
                actor=engineer_email,
                input_checks=False,
            )
        try:
            result = await client.checkin_asset(
                handover.snipeit_asset_id, "Taken back for maintenance"
            )
            refreshed = await client.get_asset(handover.snipeit_asset_id)
        except SnipeItError as exc:
            return await self._core.record_operation(
                case_id,
                Operation.TAKEN_BACK,
                status=StageStatus.FAILED,
                reason=str(exc),
                detail={},
                actor=engineer_email,
                input_checks=False,
            )
        passed = result.status == "success" and refreshed.assigned_to_id is None
        if passed:
            handover.recipient_snipeit_name = None
            await self._session.flush()
        return await self._core.record_operation(
            case_id,
            Operation.TAKEN_BACK,
            status=StageStatus.PASSED if passed else StageStatus.FAILED,
            reason=None if passed else "Device is still assigned",
            detail={"previous_assignee": asset.assigned_to_name},
            actor=engineer_email,
            input_checks=False,
        )

    async def list_cases(
        self,
        *,
        state: str | None = None,
        company: str | None = None,
        model: str | None = None,
        vendor_id: int | None = None,
        q: str | None = None,
    ) -> list[MaintenanceCaseOut]:
        rows = await self._repository.list_case_rows(
            state=state, company=company, model=model, vendor_id=vendor_id, q=q
        )
        today = date.today()
        return [
            MaintenanceCaseOut(
                **row,
                days=days_in_maintenance(
                    row["received_date"], row["returned_date"], today
                ),
            )
            for row in rows
        ]

    async def batch_send(
        self,
        case_ids: list[uuid.UUID],
        *,
        vendor_id: int,
        sent_date: date,
        engineer_email: str,
    ) -> list[MaintenanceBatchResult]:
        if sent_date > date.today():
            raise MaintenanceReasonInvalid("Sent date cannot be in the future.")
        vendor = await self._repository.get_destination(vendor_id)
        if vendor is None:
            raise MaintenanceReasonInvalid("Vendor was not found.")
        results: list[MaintenanceBatchResult] = []
        for case_id in case_ids:
            try:
                handover = await self._core.get(case_id, with_details=True)
                current_state = (
                    derive_maintenance_state(
                        {s.stage: s.status for s in handover.stages}
                    ).value
                    if handover.stages
                    else (handover.maintenance_state or MaintenanceState.WITH_IT.value)
                )
                if current_state != MaintenanceState.WITH_IT.value:
                    raise CaseStateConflict("Not with IT.")
                if handover.maintenance is None:
                    handover.maintenance = MaintenanceInfo(handover_id=handover.id)
                    self._session.add(handover.maintenance)
                handover.maintenance.destination_id = vendor.id
                handover.maintenance.destination = vendor
                handover.maintenance.sent_date = sent_date
                await self._session.flush()
                await self._core.record_operation(
                    case_id,
                    Operation.SENT_OUT,
                    status=StageStatus.PASSED,
                    reason=None,
                    detail={
                        "vendor_id": vendor.id,
                        "vendor": vendor.name,
                    },
                    actor=engineer_email,
                    input_checks=False,
                )
                results.append(MaintenanceBatchResult(case_id=case_id, ok=True))
            except HandoverError as exc:
                results.append(
                    MaintenanceBatchResult(case_id=case_id, ok=False, error=str(exc))
                )
        return results

    async def batch_receive(
        self,
        case_ids: list[uuid.UUID],
        *,
        returned_date: date,
        engineer_email: str,
        client: SnipeItClient,
    ) -> list[MaintenanceBatchResult]:
        if returned_date > date.today():
            raise MaintenanceReasonInvalid("Returned date cannot be in the future.")
        results: list[MaintenanceBatchResult] = []
        for case_id in case_ids:
            try:
                handover = await self._core.get(case_id, with_details=True)
                current_state = (
                    derive_maintenance_state(
                        {s.stage: s.status for s in handover.stages}
                    ).value
                    if handover.stages
                    else (handover.maintenance_state or MaintenanceState.WITH_IT.value)
                )
                if current_state != MaintenanceState.AT_VENDOR.value:
                    raise CaseStateConflict("The device is not at the vendor.")
                sent_date = (
                    handover.maintenance.sent_date
                    if handover.maintenance is not None
                    else None
                )
                if sent_date is not None and returned_date < sent_date:
                    raise MaintenanceReasonInvalid(
                        "Returned date cannot be before the sent date."
                    )
                if handover.maintenance is not None:
                    handover.maintenance.returned_date = returned_date
                    await self._session.flush()
                await self._core.record_operation(
                    case_id,
                    Operation.RETURNED,
                    status=StageStatus.PASSED,
                    reason=None,
                    detail={},
                    actor=engineer_email,
                    input_checks=False,
                )
                await self._set_ready_status(
                    case_id,
                    engineer_email=engineer_email,
                    client=client,
                )
                results.append(MaintenanceBatchResult(case_id=case_id, ok=True))
            except HandoverError as exc:
                results.append(
                    MaintenanceBatchResult(case_id=case_id, ok=False, error=str(exc))
                )
        return results

    async def ready_status(
        self,
        case_id: uuid.UUID,
        *,
        engineer_email: str,
        client: SnipeItClient,
    ) -> HandoverDetailView:
        return await self._set_ready_status(
            case_id, engineer_email=engineer_email, client=client
        )

    async def _set_ready_status(
        self,
        case_id: uuid.UUID,
        *,
        engineer_email: str,
        client: SnipeItClient,
    ) -> HandoverDetailView:
        handover = await self._core.get(case_id, with_details=True)
        if handover.snipeit_asset_id is None:
            raise MaintenanceReasonInvalid("The case has no Snipe-IT device.")
        label = config.SNIPEIT_STATUS_READY
        try:
            label_id = await client.find_status_label_id(label)
        except SnipeItError as exc:
            await self._core.record_operation(
                case_id,
                Operation.READY_STATUS,
                status=StageStatus.FAILED,
                reason=str(exc),
                detail={"label": label},
                actor=engineer_email,
                input_checks=False,
            )
            raise MaintenanceReasonInvalid(str(exc)) from exc
        if label_id is None:
            await self._core.record_operation(
                case_id,
                Operation.READY_STATUS,
                status=StageStatus.FAILED,
                reason=f'Status label "{label}" not found in Snipe-IT',
                detail={"label": label},
                actor=engineer_email,
                input_checks=False,
            )
            raise MaintenanceLabelNotFound(label)
        try:
            result = await client.update_asset_status(handover.snipeit_asset_id, label_id)
            asset = await client.get_asset(handover.snipeit_asset_id)
        except SnipeItError as exc:
            await self._core.record_operation(
                case_id,
                Operation.READY_STATUS,
                status=StageStatus.FAILED,
                reason=str(exc),
                detail={"label": label},
                actor=engineer_email,
                input_checks=False,
            )
            raise MaintenanceReasonInvalid(str(exc)) from exc
        matched = str(asset.status or "").strip().casefold() == label.strip().casefold()
        if matched and result.status == "success":
            handover.snipeit_status_name = asset.status
            await self._session.flush()
            return await self._core.record_operation(
                case_id,
                Operation.READY_STATUS,
                status=StageStatus.PASSED,
                reason=None,
                detail={"label": label, "status": asset.status},
                actor=engineer_email,
                input_checks=False,
            )
        await self._core.record_operation(
            case_id,
            Operation.READY_STATUS,
            status=StageStatus.FAILED,
            reason=f"Status is {asset.status}",
            detail={"label": label, "status": asset.status},
            actor=engineer_email,
            input_checks=False,
        )
        raise MaintenanceReasonInvalid(f"Status is {asset.status}")

