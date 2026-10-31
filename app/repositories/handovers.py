"""Queries for handovers and their stages (ARC-02).

Services own transactions; this module only reads and flushes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.handover import AgentReport, Handover, HandoverStage
from app.domain.stages import HandoverStatus, Stage


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
            )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def find_active_by_serial(self, serial: str) -> Handover | None:
        """An active handover is any status except completed or cancelled."""
        result = await self._session.execute(
            select(Handover).where(
                Handover.device_serial == serial,
                Handover.status.not_in(
                    [HandoverStatus.COMPLETED.value, HandoverStatus.CANCELLED.value]
                ),
            )
        )
        return result.scalars().first()

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
        filters = []
        if status is not None:
            filters.append(Handover.status == status)
        if engineer is not None:
            filters.append(Handover.engineer_email == engineer)
        if created_from is not None:
            filters.append(Handover.created_at >= created_from)
        if created_to is not None:
            filters.append(Handover.created_at <= created_to)

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
