"""Handover orchestration: creation, manual stages, cancellation, agent reports.

All business decisions are delegated to ``app.domain``; this module owns
persistence order, events and the single place the stored status is written
(``recompute_status``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.handover import Event, Handover, HandoverStage
from app.domain.errors import (
    HandoverAlreadyExists,
    HandoverCancelled,
    HandoverCompleted,
    HandoverNotFound,
    InvalidStage,
    ManualStageRequired,
    StageNotRunnable,
)
from app.domain.handover_rules import StageState, can_run, derive_status, missing_steps
from app.domain.redaction import redact_agent_payload
from app.domain.stages import (
    MANUAL_STAGES,
    STAGE_ORDER,
    HandoverStatus,
    Stage,
    StageStatus,
    stage_from_key,
)
from app.repositories.events import EventRepository
from app.repositories.handovers import HandoverRepository

SERIAL_MISMATCH_REASON = (
    "Report serial does not match the handover device serial."
)
SERIAL_MISSING_REASON = "Agent report did not include a serial number."


@dataclass(frozen=True)
class HandoverDetailView:
    """Everything the detail endpoint and its DTO need, in stage order."""

    handover: Handover
    stages: list[HandoverStage]
    events: list[Event]
    missing_steps: list[dict[str, Any]]


class HandoverService:
    """One handover use case per public method; no HTTP, no commits."""

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
        return await self._view(await self.get(handover_id, with_details=True))

    async def list(
        self,
        *,
        status: str | None = None,
        engineer: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[Handover], int]:
        return await self._handovers.list(
            status=status,
            engineer=engineer,
            created_from=created_from,
            created_to=created_to,
            page=page,
            page_size=page_size,
        )

    # -- commands ---------------------------------------------------------
    async def create(
        self,
        *,
        device_serial: str,
        engineer_email: str,
        engineer_name: str = "",
        ticket_ref: str | None = None,
    ) -> Handover:
        """Create a handover with all nine stages pending, then log it."""
        serial = device_serial.strip()
        if not serial:
            raise ValueError("device_serial must not be blank.")

        existing = await self._handovers.find_active_by_serial(serial)
        if existing is not None:
            raise HandoverAlreadyExists(
                f"An active handover already exists for serial {serial}."
            )

        handover = Handover(
            ticket_ref=(ticket_ref or "").strip() or None,
            status=HandoverStatus.DRAFT.value,
            engineer_email=engineer_email,
            engineer_name=engineer_name,
            device_serial=serial,
            stages=[
                HandoverStage(stage=stage.value, status=StageStatus.PENDING.value)
                for stage in STAGE_ORDER
            ],
        )
        try:
            await self._handovers.add(handover)
        except IntegrityError as exc:
            # The partial unique index is the last line of defence against a
            # concurrent create; the request transaction is rolled back by
            # get_session, so the service only translates the error.
            raise HandoverAlreadyExists(
                f"An active handover already exists for serial {serial}."
            ) from exc

        await self._events.add(
            handover_id=handover.id,
            actor=engineer_email,
            type="handover_created",
            detail={"device_serial": serial, "ticket_ref": handover.ticket_ref},
        )
        await self.recompute_status(handover)
        return handover

    async def confirm_manual_stage(
        self,
        handover_id: uuid.UUID,
        stage: str | Stage,
        *,
        actor: str,
    ) -> HandoverDetailView:
        """Confirm one of the four engineer-confirmed stages."""
        stage_enum = self._parse_stage(stage)
        if stage_enum not in MANUAL_STAGES:
            raise ManualStageRequired(
                f"Stage '{stage_enum.value}' cannot be confirmed manually."
            )

        handover = await self.get(handover_id, with_details=True)
        self._ensure_open(handover)

        allowed, reason = can_run(stage_enum, self._states(handover))
        if not allowed:
            raise StageNotRunnable(reason)

        row = self._stage_row(handover, stage_enum)
        row.status = StageStatus.PASSED.value
        row.reason = None
        row.actor = actor
        row.updated_at = _utcnow()

        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="stage_confirmed",
            detail={"stage": stage_enum.value},
        )
        await self.recompute_status(handover)
        return await self._view(handover)

    async def cancel(
        self, handover_id: uuid.UUID, *, actor: str
    ) -> HandoverDetailView:
        """Cancel an open handover. Cancelling twice is a no-op."""
        handover = await self.get(handover_id, with_details=True)
        if handover.status == HandoverStatus.CANCELLED.value:
            return await self._view(handover)
        if handover.status == HandoverStatus.COMPLETED.value:
            raise HandoverCompleted("Completed handovers cannot be cancelled.")

        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="handover_cancelled",
            detail={},
        )
        await self.recompute_status(handover, cancelled=True)
        return await self._view(handover)

    async def recompute_status(
        self, handover: Handover, *, cancelled: bool | None = None
    ) -> HandoverStatus:
        """Derive and store the handover status. The ONLY status writer."""
        if cancelled is None:
            cancelled = handover.status == HandoverStatus.CANCELLED.value
        status = derive_status(self._states(handover), cancelled=cancelled)
        handover.status = status.value
        if status in (HandoverStatus.COMPLETED, HandoverStatus.CANCELLED):
            if handover.closed_at is None:
                handover.closed_at = _utcnow()
        await self._session.flush()
        return status

    async def record_agent_report(
        self,
        handover_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> Handover:
        """Store a redacted report and pass/fail stage 3 by serial equality.

        The reported ``username`` is an untrusted assertion; it is only stored
        as ``recipient_reported_username`` and is never used for Snipe-IT
        writes without an engineer confirmation (Phase 5).
        """
        handover = await self.get(handover_id, with_details=True)
        self._ensure_open(handover)

        redacted = redact_agent_payload(payload)
        await self._handovers.add_agent_report(
            handover_id=handover.id, payload=redacted
        )

        reported_username = payload.get("username")
        if reported_username is None:
            handover.recipient_reported_username = None
        else:
            handover.recipient_reported_username = (
                str(reported_username).strip() or None
            )

        reported_serial = payload.get("serial")
        reported_serial = (
            str(reported_serial).strip() if reported_serial is not None else ""
        )
        expected_serial = handover.device_serial.strip()
        matched = bool(reported_serial) and reported_serial == expected_serial

        row = self._stage_row(handover, Stage.AGENT_REPORT)
        row.actor = actor
        row.updated_at = _utcnow()
        if matched:
            row.status = StageStatus.PASSED.value
            row.reason = None
            row.detail = {"reported_serial": reported_serial}
        else:
            row.status = StageStatus.FAILED.value
            row.reason = (
                SERIAL_MISSING_REASON if not reported_serial else SERIAL_MISMATCH_REASON
            )
            row.detail = {
                "reported_serial": reported_serial or None,
                "expected_serial": expected_serial,
            }

        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="agent_report_received",
            detail={
                "stage": Stage.AGENT_REPORT.value,
                "matched": matched,
                "reported_serial": reported_serial or None,
            },
        )
        await self.recompute_status(handover)
        return handover

    # -- internals --------------------------------------------------------
    async def _view(self, handover: Handover) -> HandoverDetailView:
        states = self._states(handover)
        rows = {row.stage: row for row in handover.stages}
        stages = [
            rows[stage.value] for stage in STAGE_ORDER if stage.value in rows
        ]
        events = await self._events.list_for_handover(handover.id)
        return HandoverDetailView(
            handover=handover,
            stages=stages,
            events=events,
            missing_steps=missing_steps(states),
        )

    @staticmethod
    def _states(handover: Handover) -> list[StageState]:
        rows = {row.stage: row for row in handover.stages}
        states: list[StageState] = []
        for stage in STAGE_ORDER:
            row = rows.get(stage.value)
            if row is None:
                states.append(StageState(stage))
            else:
                states.append(
                    StageState(
                        stage,
                        StageStatus(row.status),
                        row.reason,
                    )
                )
        return states

    @staticmethod
    def _stage_row(handover: Handover, stage: Stage) -> HandoverStage:
        for row in handover.stages:
            if row.stage == stage.value:
                return row
        raise HandoverNotFound(
            f"Handover {handover.id} has no '{stage.value}' stage."
        )

    @staticmethod
    def _parse_stage(stage: str | Stage) -> Stage:
        if isinstance(stage, Stage):
            return stage
        try:
            return stage_from_key(stage)
        except ValueError as exc:
            raise InvalidStage(stage) from exc

    @staticmethod
    def _ensure_open(handover: Handover) -> None:
        if handover.status == HandoverStatus.CANCELLED.value:
            raise HandoverCancelled("This handover is cancelled.")
        if handover.status == HandoverStatus.COMPLETED.value:
            raise HandoverCompleted("This handover is completed.")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
