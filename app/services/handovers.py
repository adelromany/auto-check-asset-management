"""Case orchestration: creation, independent operations, closing, agent reports.

Every business decision is delegated to ``app.domain``; this module owns
persistence order, events and the single place the stored status is written
(``recompute_status``). Operations are independent: nothing here checks that
another operation is done before letting one run (BIZ-19).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.clients.snipeit import SnipeItClient, SnipeItError, SnipeItNotFound
from app.db.models.handover import Event, Handover, HandoverStage
from app.db.models.maintenance import MaintenanceInfo
from app.domain.maintenance_rules import MaintenanceState, derive_maintenance_state
from app.repositories.maintenance import MaintenanceRepository
from app.domain.catalog import (
    MANUAL_OPERATIONS,
    NOT_DONE_REASON_MAX,
    NOT_DONE_REASON_MIN,
    CaseKind,
    Operation,
    operation_title,
    operations_for,
)
from app.domain.errors import (
    CaseStateConflict,
    ClosingConfirmationRequired,
    DeviceNotInSnipeIt,
    HandoverAlreadyExists,
    HandoverCancelled,
    HandoverCompleted,
    HandoverNotFound,
    InputMissing,
    InvalidStage,
    ManualStageRequired,
    NotDoneReasonRequired,
    OperationNotInKind,
    SnipeItUnreachable,
)
from app.domain.handover_rules import (
    StageState,
    advice,
    derive_status,
    gaps,
    missing_steps,
    performed_before,
)
from app.domain.company_rules import company_conflict, company_known
from app.domain.redaction import redact_agent_payload
from app.domain.recipient_identity import detect_recipient
from app.domain.software_rules import evaluate_hardware, evaluate_software
from app.domain.stages import (
    HandoverStatus,
    StageStatus,
    stage_from_key,
)
from app.domain.timeutil import as_utc
from app.repositories.events import EventRepository
from app.repositories.handovers import HandoverRepository

SERIAL_MISMATCH_REASON = (
    "Report serial does not match the handover device serial."
)
SERIAL_MISSING_REASON = "Agent report did not include a serial number."
SERIAL_DIFFERS_WARNING = "report serial differs"
CLOSE_CONFIRMATION = "CLOSE"

_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


def _lock_for(handover_id: uuid.UUID, operation: Operation) -> asyncio.Lock:
    """Serialize one operation of one case in-process (single process app)."""
    key = (str(handover_id), operation.value)
    lock = _LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    return lock


@dataclass(frozen=True)
class HandoverDetailView:
    """Everything the detail endpoint and its DTO need, in operation order."""

    handover: Handover
    stages: list[HandoverStage]
    events: list[Event]
    missing_steps: list[dict[str, Any]]


class HandoverService:
    """One case use case per public method; no HTTP, no commits."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._handovers = HandoverRepository(session)
        self._events = EventRepository(session)

    # -- reads ------------------------------------------------------------
    async def get(
        self, handover_id: uuid.UUID, *, with_details: bool = True
    ) -> Handover:
        handover = await self._handovers.get(handover_id, with_details=with_details)
        if handover is None:
            raise HandoverNotFound(f"Handover {handover_id} was not found.")
        return handover

    async def get_detail(self, handover_id: uuid.UUID) -> HandoverDetailView:
        return await self.view(await self.get(handover_id, with_details=True))

    async def latest_agent_report(self, handover_id: uuid.UUID):
        return await self._handovers.latest_agent_report(handover_id)

    async def find_active_by_serial(self, serial: str) -> Handover | None:
        return await self._handovers.find_active_by_serial(serial.strip())

    async def search_snipeit_users(
        self,
        handover_id: uuid.UUID,
        query: str,
        *,
        client: SnipeItClient,
    ) -> list[dict[str, Any]]:
        """Search recipient candidates and compare their company to the device."""
        handover = await self.get(handover_id, with_details=False)
        users = await client.search_users(query.strip(), limit=10)
        results: list[dict[str, Any]] = []
        for user in users:
            if company_known(handover.device_company) and company_known(user.company):
                same_company: bool | None = not company_conflict(
                    handover.device_company, user.company
                )
            else:
                same_company = None
            results.append(
                {
                    "id": user.id,
                    "name": user.name,
                    "email": user.email,
                    "username": user.username,
                    "company": user.company,
                    "same_company": same_company,
                }
            )
        return results

    async def list(
        self,
        *,
        status: str | None = None,
        engineer: str | None = None,
        kind: str | None = None,
        q: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        page: int = 1,
        page_size: int = 25,
        stall_cutoff: datetime | None = None,
    ) -> tuple[list[Handover], int]:
        return await self._handovers.list(
            status=status,
            engineer=engineer,
            kind=kind,
            q=q,
            created_from=created_from,
            created_to=created_to,
            page=page,
            page_size=page_size,
            stall_cutoff=stall_cutoff,
        )

    # -- creation ---------------------------------------------------------
    async def create(
        self,
        *,
        device_serial: str,
        engineer_email: str,
        engineer_name: str = "",
        ticket_ref: str | None = None,
        kind: CaseKind | str = CaseKind.HANDOVER,
        client: SnipeItClient | None = None,
    ) -> Handover:
        """Create a case with every operation pending, then log it once.

        A handover case reads its device facts from Snipe-IT before anything
        is stored: an unknown serial creates nothing (422) and an unreachable
        Snipe-IT creates nothing (503).
        """
        serial = device_serial.strip()
        if not serial:
            raise ValueError("device_serial must not be blank.")
        resolved_kind = CaseKind(str(kind))

        existing = await self._handovers.find_active_by_serial(serial)
        if existing is not None:
            raise HandoverAlreadyExists(active_case_message(existing, serial))

        device = await self._read_device_facts(serial, resolved_kind, client)

        handover = Handover(
            ticket_ref=(ticket_ref or "").strip() or None,
            kind=resolved_kind.value,
            status=HandoverStatus.DRAFT.value,
            engineer_email=engineer_email,
            engineer_name=engineer_name,
            device_serial=serial,
            stages=[
                HandoverStage(stage=operation.value, status=StageStatus.PENDING.value)
                for operation in operations_for(resolved_kind)
            ],
        )
        if device is not None:
            handover.snipeit_asset_id = device.id
            handover.snipeit_asset_tag = device.asset_tag
            handover.device_company = device.company
            handover.device_model = device.model
            handover.device_category = device.category
            handover.snipeit_status_name = device.status
        if resolved_kind == CaseKind.MAINTENANCE:
            handover.maintenance_state = MaintenanceState.NEEDS_MAINTENANCE.value
            handover.maintenance = MaintenanceInfo(handover_id=handover.id)
        else:
            handover.maintenance = None
        try:
            await self._handovers.add(handover)
        except IntegrityError as exc:
            raise HandoverAlreadyExists(
                f"An active case already exists for serial {serial}."
            ) from exc

        # A5: the case record already holds the serial and ticket, so the
        # creation event repeats neither.
        await self._events.add(
            handover_id=handover.id,
            actor=engineer_email,
            type="handover_created",
            detail={},
        )
        await self.recompute_status(handover)
        return handover

    async def _read_device_facts(
        self,
        serial: str,
        kind: CaseKind,
        client: SnipeItClient | None,
    ):
        """Read the device facts of a handover device from Snipe-IT.

        Returns ``None`` when no client is available (maintenance cases and
        callers that only use the local database).
        """
        if kind is not CaseKind.HANDOVER or client is None:
            return None
        try:
            return await client.get_asset_by_serial(serial)
        except SnipeItNotFound as exc:
            raise DeviceNotInSnipeIt() from exc
        except SnipeItError as exc:
            raise SnipeItUnreachable() from exc

    # -- independent operations ------------------------------------------
    async def confirm_manual_stage(
        self,
        handover_id: uuid.UUID,
        stage: str | Operation,
        *,
        actor: str,
    ) -> HandoverDetailView:
        """Confirm one of the engineer-confirmed operations (no ordering gate)."""
        operation = self._parse_stage(stage)
        if operation not in MANUAL_OPERATIONS:
            raise ManualStageRequired(
                f"Operation '{operation.value}' cannot be confirmed manually."
            )
        return await self.record_operation(
            handover_id,
            operation,
            status=StageStatus.PASSED,
            reason=None,
            detail={},
            actor=actor,
        )

    async def record_operation(
        self,
        handover_id: uuid.UUID,
        operation: str | Operation,
        *,
        status: StageStatus,
        reason: str | None,
        detail: dict[str, Any] | None,
        actor: str,
        input_checks: bool = True,
    ) -> HandoverDetailView:
        """Write exactly one outcome and one event for one operation.

        Idempotent: an identical outcome produces no second write and no
        second event. A lock per (case, operation) serializes same-operation
        requests without touching other operations of the same case.
        """
        parsed = self._parse_stage(operation)
        async with _lock_for(handover_id, parsed):
            handover = await self.get(handover_id, with_details=True)
            self._ensure_open(handover)
            self._ensure_in_kind(handover, parsed)
            if input_checks:
                await self._check_inputs(handover, parsed)

            row = stage_row(handover, parsed)
            if row.status == status.value and (row.reason or "") == (reason or ""):
                return await self.view(handover)

            states = stage_states(handover)
            prior = performed_before(parsed, states)
            hints = advice(parsed, states)
            row_detail = dict(detail or {})
            if reason:
                row_detail.setdefault("message", reason)
            if prior:
                row_detail["performed_before"] = prior
            if hints:
                row_detail["advice"] = hints

            changed = await self._handovers.compare_and_set_stage(
                row.id,
                status=status.value,
                reason=reason,
                detail=row_detail,
                actor=actor,
                now=_utcnow(),
            )
            if changed:
                if handover.kind == CaseKind.MAINTENANCE.value and parsed in (
                    Operation.RECEIVED,
                    Operation.DIAGNOSIS,
                    Operation.SENT_OUT,
                    Operation.RETURNED,
                    Operation.SNIPEIT_STATUS,
                ):
                    if handover.maintenance is None:
                        handover.maintenance = MaintenanceInfo(handover_id=handover.id)
                        self._session.add(handover.maintenance)
                    m_repo = MaintenanceRepository(self._session)
                    m_fields = dict(detail or {})
                    if (
                        parsed == Operation.SENT_OUT
                        and status == StageStatus.PASSED
                        and not handover.maintenance.sent_date
                        and "sent_date" not in m_fields
                    ):
                        m_fields["sent_date"] = _utcnow().date()
                    if (
                        parsed == Operation.RETURNED
                        and status == StageStatus.PASSED
                        and not handover.maintenance.returned_date
                        and "returned_date" not in m_fields
                    ):
                        m_fields["returned_date"] = _utcnow().date()
                    if m_fields:
                        await m_repo.apply_fields(handover.maintenance, m_fields)

                event_detail: dict[str, Any] = {
                    "operation": parsed.value,
                    "outcome": status.value,
                }
                if reason:
                    event_detail["reason"] = reason
                if prior:
                    event_detail["performed_before"] = prior
                await self._events.add(
                    handover_id=handover.id,
                    actor=actor,
                    type="operation_recorded",
                    detail=event_detail,
                )
            return await self._recompute_and_view(handover.id)

    async def mark_not_done(
        self,
        handover_id: uuid.UUID,
        operation: str | Operation,
        *,
        reason: str,
        actor: str,
    ) -> HandoverDetailView:
        """Explicitly record that this operation was not done (reason mandatory)."""
        cleaned = validate_not_done_reason(reason)
        return await self.record_operation(
            handover_id,
            operation,
            status=StageStatus.NOT_DONE,
            reason=cleaned,
            detail={},
            actor=actor,
            input_checks=False,
        )

    async def retry_operation(
        self,
        handover_id: uuid.UUID,
        operation: str | Operation,
        *,
        actor: str,
    ) -> HandoverDetailView:
        """Put a failed/not-done operation back to pending so it can run again."""
        parsed = self._parse_stage(operation)
        async with _lock_for(handover_id, parsed):
            handover = await self.get(handover_id, with_details=True)
            self._ensure_open(handover)
            self._ensure_in_kind(handover, parsed)
            row = stage_row(handover, parsed)
            if row.status == StageStatus.PENDING.value:
                return await self.view(handover)
            changed = await self._handovers.compare_and_set_stage(
                row.id,
                status=StageStatus.PENDING.value,
                reason=None,
                detail={},
                actor=actor,
                now=_utcnow(),
            )
            if changed:
                await self._events.add(
                    handover_id=handover.id,
                    actor=actor,
                    type="operation_recorded",
                    detail={"operation": parsed.value, "outcome": "pending"},
                )
            return await self._recompute_and_view(handover.id)

    # -- case closing -----------------------------------------------------
    async def cancel(
        self, handover_id: uuid.UUID, *, actor: str
    ) -> HandoverDetailView:
        """Cancel an open case. Cancelling twice is a no-op."""
        handover = await self.get(handover_id, with_details=True)
        if handover.status == HandoverStatus.CANCELLED.value:
            return await self.view(handover)
        if handover.status == HandoverStatus.COMPLETED.value:
            raise HandoverCompleted("Completed cases cannot be cancelled.")
        if handover.status == HandoverStatus.CLOSED_WITH_GAPS.value:
            raise CaseStateConflict(
                "A case closed with gaps must be reopened before it can be cancelled."
            )

        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="handover_cancelled",
            detail={},
        )
        await self.recompute_status(handover, cancelled=True)
        return await self.view(handover)

    async def close_with_gaps(
        self, handover_id: uuid.UUID, *, confirmation: str, actor: str
    ) -> HandoverDetailView:
        """Close an open case while recording every operation that is not done."""
        handover = await self.get(handover_id, with_details=True)
        self._ensure_open(handover)
        if (confirmation or "").strip().upper() != CLOSE_CONFIRMATION:
            raise ClosingConfirmationRequired()
        gap_list = gaps(stage_states(handover))
        if not gap_list:
            raise CaseStateConflict(
                "Every operation is done; the case completes on its own."
            )

        now = _utcnow()
        handover.closed_gaps = gap_list
        handover.closed_at = now
        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="case_closed_with_gaps",
            detail={"gaps": gap_list},
        )
        await self.recompute_status(handover, closed_with_gaps=True)
        return await self.view(handover)

    async def reopen(
        self, handover_id: uuid.UUID, *, actor: str
    ) -> HandoverDetailView:
        """Reopen only a ``closed_with_gaps`` case so a missing operation can run."""
        handover = await self.get(handover_id, with_details=True)
        if handover.status != HandoverStatus.CLOSED_WITH_GAPS.value:
            raise CaseStateConflict("Only a case closed with gaps can be reopened.")
        handover.closed_gaps = None
        handover.closed_at = None
        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="case_reopened",
            detail={},
        )
        await self.recompute_status(handover, closed_with_gaps=False)
        return await self.view(handover)

    # -- status -----------------------------------------------------------
    async def update_maintenance_info(
        self,
        handover_id: uuid.UUID,
        fields: dict[str, Any],
        *,
        actor: str,
    ) -> HandoverDetailView:
        """Update typed maintenance fields on a maintenance case."""
        handover = await self.get(handover_id, with_details=True)
        self._ensure_open(handover)
        if handover.kind != CaseKind.MAINTENANCE.value:
            raise CaseStateConflict(
                "Cannot update maintenance fields on a non-maintenance case."
            )
        if handover.maintenance is None:
            handover.maintenance = MaintenanceInfo(handover_id=handover.id)
            self._session.add(handover.maintenance)
        m_repo = MaintenanceRepository(self._session)
        changed = await m_repo.apply_fields(handover.maintenance, fields)
        if changed:
            await self._events.add(
                handover_id=handover.id,
                actor=actor,
                type="maintenance_updated",
                detail={"changed_fields": changed},
            )
            await self.recompute_status(handover)
        return await self.view(handover)

    async def recompute_status(
        self,
        handover: Handover,
        *,
        cancelled: bool | None = None,
        closed_with_gaps: bool | None = None,
    ) -> HandoverStatus:
        """Derive and store the case status. The ONLY status writer."""
        if cancelled is None:
            cancelled = handover.status == HandoverStatus.CANCELLED.value
        if closed_with_gaps is None:
            closed_with_gaps = handover.closed_gaps is not None
        now = _utcnow()
        handover.updated_at = now
        status = derive_status(
            stage_states(handover),
            operations=operations_for(handover.kind or CaseKind.HANDOVER.value),
            cancelled=cancelled,
            closed_with_gaps=closed_with_gaps,
            updated_at=as_utc(handover.updated_at),
            now=now,
            stall_hours=config.STALL_HOURS,
        )
        handover.status = status.value
        if handover.kind == CaseKind.MAINTENANCE.value:
            st_dict = {s.stage: s.status for s in handover.stages}
            handover.maintenance_state = derive_maintenance_state(st_dict).value
        if status in (
            HandoverStatus.COMPLETED,
            HandoverStatus.CANCELLED,
            HandoverStatus.CLOSED_WITH_GAPS,
        ):
            if handover.closed_at is None:
                handover.closed_at = now
        else:
            handover.closed_at = None
        await self._session.flush()
        return status

    # -- agent report -----------------------------------------------------
    async def record_agent_report(
        self,
        handover_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> Handover:
        """Store one report and record hardware, software and identity apart.

        The operations do not depend on each other: software is evaluated
        even when the hardware result failed, and a serial mismatch only
        fails the Agent report operation and flags the Software operation.
        """
        handover = await self.get(handover_id, with_details=True)
        self._ensure_open(handover)
        self._ensure_in_kind(handover, Operation.AGENT_REPORT)

        redacted = redact_agent_payload(payload)
        await self._handovers.add_agent_report(
            handover_id=handover.id, payload=redacted
        )

        detected_user = detect_recipient(payload, handover.engineer_email)
        handover.recipient_reported_username = detected_user.sam or None
        recipient_row = stage_row(handover, Operation.RECIPIENT_CHECK)
        if recipient_row.status != StageStatus.PASSED.value:
            recipient_row.detail = {
                **(recipient_row.detail or {}),
                "detected_user": detected_user.raw or None,
                "is_local": detected_user.is_local,
                "same_as_engineer": detected_user.same_as_engineer,
            }
        await self._session.flush()

        hardware_result = evaluate_hardware(redacted, handover.device_serial)
        reported_serial = str(payload.get("serial") or "").strip()
        reason = hardware_result.message
        mismatch = False
        if not reported_serial:
            reason = SERIAL_MISSING_REASON
            mismatch = True
        elif reported_serial.casefold() != handover.device_serial.strip().casefold():
            reason = SERIAL_MISMATCH_REASON
            mismatch = True

        await self.record_operation(
            handover.id,
            Operation.AGENT_REPORT,
            status=hardware_result.status,
            reason=reason if hardware_result.status is StageStatus.FAILED else None,
            detail={**hardware_result.detail, "message": hardware_result.message},
            actor=actor,
            input_checks=False,
        )

        software_row = await self._stage_row_fresh(handover.id, Operation.SOFTWARE_CHECK)
        if software_row.status != StageStatus.NOT_DONE.value:
            software_result = evaluate_software(redacted, config.REQUIRED_SOFTWARE_IDS)
            software_detail = {
                **software_result.detail,
                "message": software_result.message,
            }
            if mismatch:
                software_detail["report_serial_differs"] = True
                software_detail["warnings"] = [SERIAL_DIFFERS_WARNING]
            await self.record_operation(
                handover.id,
                Operation.SOFTWARE_CHECK,
                status=software_result.status,
                reason=(
                    software_result.message
                    if software_result.status is StageStatus.FAILED
                    else None
                ),
                detail=software_detail,
                actor=actor,
                input_checks=False,
            )

        return await self.get(handover_id, with_details=True)

    # -- internals --------------------------------------------------------
    async def view(self, handover: Handover) -> HandoverDetailView:
        states = stage_states(handover)
        rows = {row.stage: row for row in handover.stages}
        ordered = [
            rows[operation.value]
            for operation in operations_for(handover.kind or CaseKind.HANDOVER.value)
            if operation.value in rows
        ]
        events = await self._events.list_for_handover(handover.id)
        return HandoverDetailView(
            handover=handover,
            stages=ordered,
            events=events,
            missing_steps=missing_steps(states),
        )

    async def _recompute_and_view(self, handover_id: uuid.UUID) -> HandoverDetailView:
        await self._session.flush()
        self._session.expire_all()
        handover = await self.get(handover_id, with_details=True)
        await self.recompute_status(handover)
        return await self.view(handover)

    async def _stage_row_fresh(
        self, handover_id: uuid.UUID, operation: Operation
    ) -> HandoverStage:
        self._session.expire_all()
        handover = await self.get(handover_id, with_details=True)
        return stage_row(handover, operation)

    async def _check_inputs(
        self, handover: Handover, operation: Operation
    ) -> None:
        """Fail only this operation (422) when its own input is genuinely absent."""
        if operation is Operation.CHECKOUT and handover.recipient_snipeit_id is None:
            raise InputMissing(
                "Pick a recipient first, or mark Checkout as not done."
            )
        if operation is Operation.DOCUMENT_PUSHED:
            if not handover.documents:
                raise InputMissing(
                    "Attach the signed scan first, or mark Push as not done."
                )
        if operation is Operation.REPORT_PRINTED:
            if not handover.agent_reports:
                raise InputMissing(
                    "Run the agent report first, or mark Print form as not done."
                )

    @staticmethod
    def _parse_stage(stage: str | Operation) -> Operation:
        if isinstance(stage, Operation):
            return stage
        try:
            return stage_from_key(stage)
        except ValueError as exc:
            raise InvalidStage(stage) from exc

    @staticmethod
    def _ensure_in_kind(handover: Handover, operation: Operation) -> None:
        kind = CaseKind(handover.kind or CaseKind.HANDOVER.value)
        if operation not in operations_for(kind):
            raise OperationNotInKind(operation.value, kind.value)

    @staticmethod
    def _ensure_open(handover: Handover) -> None:
        ensure_open(handover)


def validate_not_done_reason(reason: str) -> str:
    cleaned = (reason or "").strip()
    if not NOT_DONE_REASON_MIN <= len(cleaned) <= NOT_DONE_REASON_MAX:
        raise NotDoneReasonRequired(
            f"A reason of {NOT_DONE_REASON_MIN}–{NOT_DONE_REASON_MAX} characters "
            "is required to mark an operation not done."
        )
    return cleaned


def active_case_message(existing: Handover, serial: str) -> str:
    kind = existing.kind or CaseKind.HANDOVER.value
    who = existing.engineer_name or existing.engineer_email or "an engineer"
    return (
        f"Serial {serial} already has an active {kind} case "
        f"opened by {who}."
    )


def stage_states(handover: Handover) -> list[StageState]:
    """The operation states of this case in reading order, missing rows pending."""
    kind = handover.kind or CaseKind.HANDOVER.value
    rows = {row.stage: row for row in handover.stages}
    states: list[StageState] = []
    for operation in operations_for(kind):
        row = rows.get(operation.value)
        if row is None:
            states.append(StageState(operation))
        else:
            states.append(
                StageState(operation, StageStatus(row.status), row.reason)
            )
    return states


def stage_row(handover: Handover, stage: Operation) -> HandoverStage:
    """The ORM row for one operation; a missing row is a data-integrity error."""
    for row in handover.stages:
        if row.stage == stage.value:
            return row
    raise HandoverNotFound(
        f"Handover {handover.id} has no '{stage.value}' operation."
    )


def ensure_open(handover: Handover) -> None:
    """Reject work on a cancelled, completed or closed-with-gaps case."""
    if handover.status == HandoverStatus.CANCELLED.value:
        raise HandoverCancelled("This case is cancelled.")
    if handover.status == HandoverStatus.COMPLETED.value:
        raise HandoverCompleted("This case is completed.")
    if handover.status == HandoverStatus.CLOSED_WITH_GAPS.value:
        raise CaseStateConflict(
            "This case is closed with gaps; reopen it before further work."
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
