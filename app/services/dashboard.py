"""Operations dashboard aggregates (Phase 7).

Every figure is computed by the database. Python only pivots the small
(stage x status) result and zero-fills the fixed status/stage sets, so the
response shape is stable even when no handover exists.

The table rows are a page-sized read: the repository loads at most
``page_size`` handovers and their ten stages, and the pure domain rules
derive each row's missing steps. No endpoint loads the whole table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.handover import Handover, HandoverStage
from app.domain.handover_rules import missing_steps
from app.domain.timeutil import as_utc
from app import config
from app.domain.stages import (
    STAGE_ORDER,
    HandoverStatus,
    StageStatus,
)
from app.dto.dashboard import (
    DashboardSummaryOut,
    EngineerCountOut,
    HandoverRowListOut,
    HandoverRowOut,
    MissingStepCountOut,
    StageCountsOut,
    StageProgressOut,
)
from app.dto.handover import HandoverSummary, MissingStepOut
from app.services.handovers import HandoverService, stage_states

_ACTIVE_STATUSES = (
    HandoverStatus.COMPLETED.value,
    HandoverStatus.CANCELLED.value,
)


class DashboardService:
    """Read-only aggregates and paged rows for the dashboard."""

    def __init__(self, session: AsyncSession, *, now: datetime | None = None):
        self._session = session
        self._now = as_utc(now or datetime.now(timezone.utc))

    # -- summary ----------------------------------------------------------
    async def summary(
        self,
        *,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> DashboardSummaryOut:
        filters = _created_filters(created_from, created_to)

        by_status = {status.value: 0 for status in HandoverStatus}
        stale = self._stalled_by_age_condition()
        visible_status = case(
            (stale, HandoverStatus.STALLED.value), else_=Handover.status
        )
        status_rows = await self._session.execute(
            select(visible_status, func.count())
            .where(*filters)
            .group_by(visible_status)
        )
        for status, count in status_rows.all():
            if str(status) in by_status:
                by_status[str(status)] = int(count)

        stages = await self._stage_matrix(filters)
        average = await self._average_seconds(filters)
        engineers = await self._engineers(filters)
        top_missing = await self._top_missing(filters)

        return DashboardSummaryOut(
            created_from=created_from,
            created_to=created_to,
            total=sum(by_status.values()),
            completed=by_status.get(HandoverStatus.COMPLETED.value, 0),
            by_status=by_status,
            stages=stages,
            average_time_to_complete_seconds=average,
            by_engineer=engineers,
            top_missing_steps=top_missing,
        )

    async def _stage_matrix(
        self, filters: list
    ) -> dict[str, StageCountsOut]:
        matrix = {stage.value: StageCountsOut() for stage in STAGE_ORDER}
        rows = await self._session.execute(
            select(
                HandoverStage.stage,
                HandoverStage.status,
                func.count(),
            )
            .join(Handover, Handover.id == HandoverStage.handover_id)
            .where(*filters)
            .group_by(HandoverStage.stage, HandoverStage.status)
        )
        for stage_key, status_key, count in rows.all():
            bucket = matrix.get(str(stage_key))
            if bucket is None:
                continue
            if hasattr(bucket, str(status_key)):
                setattr(bucket, str(status_key), int(count))
        return matrix

    async def _average_seconds(
        self, filters: list
    ) -> float | None:
        """Average ``closed_at - created_at`` for completed handovers.

        The subtraction is done by the database. SQLite stores timestamps as
        text, so it needs ``julianday``; PostgreSQL uses epoch extraction.
        """
        completed_filters = [
            *filters,
            Handover.status == HandoverStatus.COMPLETED.value,
            Handover.closed_at.is_not(None),
        ]
        dialect = self._session.get_bind().dialect.name
        if dialect == "sqlite":
            duration = (
                func.julianday(Handover.closed_at)
                - func.julianday(Handover.created_at)
            ) * 86400.0
        else:
            duration = func.extract(
                "epoch", Handover.closed_at - Handover.created_at
            )
        value = await self._session.scalar(
            select(func.avg(duration)).where(*completed_filters)
        )
        return round(float(value), 1) if value is not None else None

    async def _engineers(
        self, filters: list
    ) -> list[EngineerCountOut]:
        completed = func.sum(
            case(
                (Handover.status == HandoverStatus.COMPLETED.value, 1),
                else_=0,
            )
        )
        total = func.count()
        rows = await self._session.execute(
            select(
                Handover.engineer_email,
                func.max(Handover.engineer_name),
                total,
                completed,
            )
            .where(*filters)
            .group_by(Handover.engineer_email)
            .order_by(total.desc(), Handover.engineer_email)
        )
        return [
            EngineerCountOut(
                email=email,
                name=name or "",
                total=int(count),
                completed=int(done or 0),
            )
            for email, name, count, done in rows.all()
        ]

    async def _top_missing(
        self, filters: list
    ) -> list[MissingStepCountOut]:
        count = func.count()
        rows = await self._session.execute(
            select(HandoverStage.stage, count)
            .join(Handover, Handover.id == HandoverStage.handover_id)
            .where(
                *filters,
                Handover.status.not_in(_ACTIVE_STATUSES),
                HandoverStage.status.not_in(
                    [StageStatus.PASSED.value, StageStatus.SKIPPED.value]
                ),
            )
            .group_by(HandoverStage.stage)
            .order_by(count.desc(), HandoverStage.stage)
            .limit(5)
        )
        return [
            MissingStepCountOut(stage=str(stage), count=int(total))
            for stage, total in rows.all()
        ]

    # -- table rows -------------------------------------------------------
    async def rows(
        self,
        *,
        status: str | None = None,
        engineer: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> HandoverRowListOut:
        service = HandoverService(self._session)
        handovers, total = await service.list(
            status=status,
            engineer=engineer,
            created_from=created_from,
            created_to=created_to,
            page=page,
            page_size=page_size,
            stall_cutoff=self._stall_cutoff(),
        )
        items = []
        for handover in handovers:
            last_updated = as_utc(handover.updated_at)
            now = as_utc(self._now)
            cutoff = self._stall_cutoff()
            if (
                cutoff is not None
                and handover.status in (HandoverStatus.DRAFT.value, HandoverStatus.IN_PROGRESS.value)
                and last_updated is not None
                and now is not None
                and last_updated < now - timedelta(hours=config.STALL_HOURS)
            ):
                handover.status = HandoverStatus.STALLED.value
            states = stage_states(handover)
            items.append(
                HandoverRowOut(
                    handover=HandoverSummary.model_validate(handover),
                    stages=[
                        StageProgressOut(
                            stage=state.stage.value,
                            status=state.status.value,
                        )
                        for state in states
                    ],
                    missing_steps=[
                        MissingStepOut(**item) for item in missing_steps(states)
                    ],
                )
            )
        return HandoverRowListOut(
            items=items, total=total, page=page, page_size=page_size
        )

    def _stall_cutoff(self) -> datetime | None:
        if config.STALL_HOURS <= 0 or self._now is None:
            return None
        return self._now - timedelta(hours=config.STALL_HOURS)

    def _stalled_by_age_condition(self):
        cutoff = self._stall_cutoff()
        if cutoff is None:
            return False
        return and_(
            Handover.status.in_(
                [HandoverStatus.DRAFT.value, HandoverStatus.IN_PROGRESS.value]
            ),
            Handover.updated_at < cutoff,
        )


def _created_filters(
    created_from: datetime | None, created_to: datetime | None
) -> list:
    filters = []
    if created_from is not None:
        filters.append(Handover.created_at >= created_from)
    if created_to is not None:
        filters.append(Handover.created_at <= created_to)
    return filters
