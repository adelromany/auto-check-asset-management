"""Queries for handovers and their stages (ARC-02).

Services own transactions; this module only reads and flushes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.handover import AgentReport, Handover, HandoverStage
from app.domain.stages import HandoverStatus, Stage
from app.repositories.filters import build_case_filters


class HandoverRepository:
    """Data access for handovers, their stages and their evidence."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, handover: Handover) -> Handover:
        self._session.add(handover)
        await self._session.flush()
        return handover

    async def add_agent_report(
        self, *, handover_id: uuid.UUID, payload: dict[str, Any]
    ) -> AgentReport:
        """Store a redacted agent report; the caller owns redaction."""
        report = AgentReport(handover_id=handover_id, payload=payload)
        self._session.add(report)
        await self._session.flush()
        return report

    async def latest_agent_report(
        self, handover_id: uuid.UUID
    ) -> AgentReport | None:
        result = await self._session.execute(
            select(AgentReport)
            .where(AgentReport.handover_id == handover_id)
            .order_by(AgentReport.received_at.desc(), AgentReport.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get(
        self, handover_id: uuid.UUID, *, with_details: bool = False
    ) -> Handover | None:
        statement = select(Handover).where(Handover.id == handover_id)
        if with_details:
            statement = statement.options(
                selectinload(Handover.stages),
                selectinload(Handover.events),
                selectinload(Handover.agent_reports),
                selectinload(Handover.documents),
                selectinload(Handover.maintenance),
            )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def find_active_by_serial(self, serial: str) -> Handover | None:
        """An active case is any status except completed, closed_gaps, cancelled."""
        result = await self._session.execute(
            select(Handover).where(
                Handover.device_serial == serial,
                Handover.status.not_in(
                    [
                        HandoverStatus.COMPLETED.value,
                        HandoverStatus.CLOSED_WITH_GAPS.value,
                        HandoverStatus.CANCELLED.value,
                    ]
                ),
            )
        )
        return result.scalars().first()

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
        filters = build_case_filters(
            status=status,
            engineer=engineer,
            kind=kind,
            q=q,
            created_from=created_from,
            created_to=created_to,
            stall_cutoff=stall_cutoff,
        )

        total = await self._session.scalar(
            select(func.count()).select_from(Handover).where(*filters)
        )
        result = await self._session.execute(
            select(Handover)
            .where(*filters)
            .options(selectinload(Handover.stages))
            .order_by(Handover.created_at.desc(), Handover.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), int(total or 0)

    async def compare_and_set_stage(
        self,
        stage_id: uuid.UUID,
        *,
        status: str,
        reason: str | None,
        detail: dict[str, Any],
        actor: str,
        now: datetime,
    ) -> int:
        """Write one outcome only when it changes the row; returns rowcount.

        Two requests for the same operation therefore produce one write and
        one event, while requests for different operations never touch the
        same row.
        """
        statement = (
            update(HandoverStage)
            .where(HandoverStage.id == stage_id)
            .where(
                or_(
                    HandoverStage.status != status,
                    func.coalesce(HandoverStage.reason, "") != (reason or ""),
                )
            )
            .values(
                status=status,
                reason=reason,
                detail=detail,
                actor=actor,
                updated_at=now,
            )
            .execution_options(synchronize_session="fetch")
        )
        result = await self._session.execute(statement)
        return int(result.rowcount or 0)

    async def get_stage(
        self, handover_id: uuid.UUID, stage: Stage
    ) -> HandoverStage | None:
        result = await self._session.execute(
            select(HandoverStage).where(
                HandoverStage.handover_id == handover_id,
                HandoverStage.stage == stage.value,
            )
        )
        return result.scalar_one_or_none()
