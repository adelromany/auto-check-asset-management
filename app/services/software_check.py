"""Software-check override and re-evaluation use cases."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.domain.errors import SoftwareCheckConflict
from app.domain.software_rules import evaluate_hardware, evaluate_software
from app.domain.stages import Stage, StageStatus
from app.repositories.events import EventRepository
from app.repositories.handovers import HandoverRepository
from app.services.handovers import (
    HandoverDetailView,
    HandoverService,
    ensure_open,
    stage_row,
)


class SoftwareCheckService:
    """Mutate software-stage state inside the caller's transaction."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._core = HandoverService(session)
        self._handovers = HandoverRepository(session)
        self._events = EventRepository(session)

    async def override(
        self,
        handover_id: uuid.UUID,
        *,
        reason: str,
        actor: str,
    ) -> HandoverDetailView:
        handover = await self._core.get(handover_id, with_details=True)
        ensure_open(handover)
        row = stage_row(handover, Stage.SOFTWARE_CHECK)
        if row.status != StageStatus.FAILED.value:
            raise SoftwareCheckConflict(
                "software_check override requires failed status; "
                f"current status is {row.status}."
            )

        cleaned_reason = reason.strip()
        if not 10 <= len(cleaned_reason) <= 500:
            raise ValueError("reason must be 10–500 characters after trimming")
        row.status = StageStatus.SKIPPED.value
        row.reason = cleaned_reason
        row.detail = {
            **(row.detail or {}),
            "override_reason": cleaned_reason,
            "overridden": True,
        }
        row.actor = actor
        row.updated_at = _utcnow()
        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="software_check_overridden",
            detail={"stage": Stage.SOFTWARE_CHECK.value, "reason": cleaned_reason},
        )
        await self._core.recompute_status(handover)
        return await self._core.view(handover)

    async def reevaluate(
        self, handover_id: uuid.UUID, *, actor: str
    ) -> HandoverDetailView:
        handover = await self._core.get(handover_id, with_details=True)
        ensure_open(handover)
        row = stage_row(handover, Stage.SOFTWARE_CHECK)
        if row.status == StageStatus.SKIPPED.value:
            raise SoftwareCheckConflict(
                "software_check was skipped by an override and cannot be re-evaluated."
            )

        report = await self._handovers.latest_agent_report(handover.id)
        if report is None:
            raise SoftwareCheckConflict(
                "software_check cannot be re-evaluated because no agent report exists."
            )

        hardware = evaluate_hardware(report.payload, handover.device_serial)
        if hardware.status is not StageStatus.PASSED:
            raise SoftwareCheckConflict(
                "software_check cannot be re-evaluated because agent_report is "
                f"{StageStatus.FAILED.value}."
            )

        result = evaluate_software(report.payload, config.REQUIRED_SOFTWARE_IDS)
        row.status = result.status.value
        row.reason = result.message if result.status is StageStatus.FAILED else None
        row.detail = {**result.detail, "message": result.message}
        row.actor = actor
        row.updated_at = _utcnow()
        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="software_check_reevaluated",
            detail={"stage": Stage.SOFTWARE_CHECK.value, "status": row.status},
        )
        await self._core.recompute_status(handover)
        return await self._core.view(handover)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
