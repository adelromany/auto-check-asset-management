"""Operations dashboard aggregates (Phase 7).

Every figure is computed by the database. Python only pivots the small
(stage x status) result and zero-fills the fixed status/stage sets, so the
response shape is stable even when no handover exists.

The table rows are a page-sized read: the repository loads at most
``page_size`` handovers and their ten stages, and the pure domain rules
derive each row's missing steps. No endpoint loads the whole table.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.handover import Event, Handover, HandoverStage
from app.domain.catalog import HANDOVER_OPERATIONS, Operation, operation_title
from app.domain.company_rules import company_conflict
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
    HandoverActivityOut,
    HandoverAttentionOut,
    HandoverCaseListOut,
    HandoverCompanyRowOut,
    HandoverDashboardOut,
    HandoverEngineerOut,
    HandoverMissingPartOut,
    HandoverOutcomeDashboardOut,
    HandoverPerDayOut,
    HandoverRowListOut,
    HandoverRowOut,
    HandoverTilesOut,
    MaintenanceDashboardOut,
    MaintenanceDeviceOut,
    MaintenanceGroupOut,
    MaintenanceSectionOut,
    MissingStepCountOut,
    ReadyCompanyOut,
    ReadyModelCompanyOut,
    ReadyModelOut,
    ReadyGroupOut,
    StageCountsOut,
    StageProgressOut,
)
from app.domain.maintenance_rules import days_in_maintenance
from app.dto.handover import HandoverSummary, MissingStepOut
from app.repositories.maintenance import MaintenanceRepository
from app.services.handovers import HandoverService, stage_states

_INACTIVE_STATUSES = (
    HandoverStatus.COMPLETED.value,
    HandoverStatus.CLOSED_WITH_GAPS.value,
    HandoverStatus.CANCELLED.value,
)


class DashboardService:
    """Read-only aggregates and paged rows for the dashboard."""

    def __init__(self, session: AsyncSession, *, now: datetime | None = None):
        self._session = session
        self._now = as_utc(now or datetime.now(timezone.utc))

    # -- handover outcome summary -----------------------------------------
    async def handover_outcomes(self) -> HandoverOutcomeDashboardOut:
        """Return handover-only outcome totals; maintenance is excluded."""
        handover_only = [Handover.kind == "handover"]
        ready_rows = await self._session.execute(
            select(Handover.device_company, func.count())
            .where(*handover_only, Handover.status == HandoverStatus.READY.value)
            .group_by(Handover.device_company)
            .order_by(Handover.device_company)
        )
        by_company = [
            ReadyCompanyOut(company=str(company or "Unknown"), count=int(count))
            for company, count in ready_rows.all()
        ]
        ready_total = sum(item.count for item in by_company)

        complete = await self._session.scalar(
            select(func.count())
            .where(
                *handover_only,
                Handover.status == HandoverStatus.COMPLETED.value,
            )
        )
        not_complete = await self._session.scalar(
            select(func.count())
            .where(
                *handover_only,
                Handover.status.not_in(
                    [
                        HandoverStatus.COMPLETED.value,
                        HandoverStatus.READY.value,
                        HandoverStatus.CANCELLED.value,
                    ]
                ),
            )
        )
        return HandoverOutcomeDashboardOut(
            ready=ReadyGroupOut(total=ready_total, by_company=by_company),
            complete={"total": int(complete or 0)},
            not_complete={"total": int(not_complete or 0)},
        )

    # -- Round 2: full handover operations dashboard ----------------------
    async def handover_dashboard(
        self, *, period: str = "30d", company: str | None = None
    ) -> HandoverDashboardOut:
        """One JSON document for every handover dashboard block."""
        period = period if period in PERIOD_DAYS else "30d"
        selected = (company or "").strip()
        rows = await self._handover_dashboard_rows()
        if selected and selected.casefold() != "all":
            rows = [
                row
                for row in rows
                if _company_label(row["device_company"]).casefold()
                == selected.casefold()
            ]

        period_start = self._period_start(period)
        open_ids = [
            row["id"] for row in rows if row["status"] not in _INACTIVE_STATUSES
        ]
        stage_rows = await self._stage_map(open_ids)

        complete_rows = [
            row for row in rows if _completed_in_period(row, period_start)
        ]
        open_rows = [
            row for row in rows if row["status"] not in _INACTIVE_STATUSES
        ]
        stalled_rows = [row for row in open_rows if self._row_stalled(row)]
        warning_rows = [
            row
            for row in rows
            if company_conflict(row["device_company"], row["recipient_company"])
            and (
                row["status"] not in _INACTIVE_STATUSES
                or _completed_in_period(row, period_start)
            )
        ]
        durations = [
            hours
            for hours in (
                _hours_between(row["created_at"], row["closed_at"])
                for row in complete_rows
            )
            if hours is not None
        ]

        tiles = HandoverTilesOut(
            ready=sum(1 for row in rows if row["status"] == HandoverStatus.READY.value),
            complete=len(complete_rows),
            not_complete=sum(
                1 for row in open_rows if row["status"] in _OPEN_STATUSES
            ),
            waiting_user=sum(
                1
                for row in open_rows
                if row["recipient_mode"] == PENDING_USER_MODE
            ),
            stalled=len(stalled_rows),
            warnings=len(warning_rows),
            avg_hours_to_complete=(
                round(sum(durations) / len(durations), 1) if durations else None
            ),
            median_hours_to_complete=(
                round(median(durations), 1) if durations else None
            ),
            within_24h_percent=(
                round(
                    sum(1 for hours in durations if hours <= 24)
                    / len(durations)
                    * 100,
                    1,
                )
                if durations
                else None
            ),
        )

        return HandoverDashboardOut(
            period=period,
            company=selected or "all",
            tiles=tiles,
            by_company=_by_company(rows, period_start),
            ready_by_model=_ready_by_model(rows),
            per_day=self._per_day(rows, period),
            missing_parts=await self._missing_parts(rows, stage_rows),
            by_engineer=_by_engineer(rows, period_start),
            attention=_attention(rows, stage_rows, self._now),
            activity=await self._activity(),
        )

    async def handover_cases(
        self,
        *,
        filter: str = "attention",
        period: str = "30d",
        company: str | None = None,
        stage: str | None = None,
        engineer: str | None = None,
    ) -> HandoverCaseListOut:
        """The bottom panel: the cases behind one clicked number or bar."""
        period = period if period in PERIOD_DAYS else "30d"
        selected = (company or "").strip()
        company_arg = (
            None if not selected or selected.casefold() == "all" else selected
        )
        service = HandoverService(self._session)
        handovers, _total = await service.list(
            kind="handover",
            company=company_arg,
            page=1,
            page_size=CASE_PANEL_LIMIT,
            stall_cutoff=self._stall_cutoff(),
        )
        period_start = self._period_start(period)
        items = [
            handover
            for handover in handovers
            if self._case_matches(
                handover,
                filter=filter,
                period_start=period_start,
                stage=stage,
                engineer=engineer,
            )
        ]
        summaries = []
        for item in items:
            if self._row_stalled(
                {"status": item.status, "updated_at": item.updated_at}
            ):
                item.status = HandoverStatus.STALLED.value
            summaries.append(HandoverSummary.model_validate(item))
        return HandoverCaseListOut(
            filter=filter,
            items=summaries,
            total=len(items),
        )

    async def _handover_dashboard_rows(self) -> list[dict]:
        result = await self._session.execute(
            select(
                Handover.id,
                Handover.status,
                Handover.device_company,
                Handover.recipient_company,
                Handover.recipient_mode,
                Handover.device_serial,
                Handover.device_model,
                Handover.recipient_snipeit_name,
                Handover.recipient_snipeit_username,
                Handover.recipient_free_name,
                Handover.engineer_name,
                Handover.created_at,
                Handover.updated_at,
                Handover.closed_at,
            )
            .where(
                Handover.kind == "handover",
                Handover.status != HandoverStatus.CANCELLED.value,
            )
            .order_by(Handover.created_at.desc())
        )
        return [dict(row._mapping) for row in result.all()]

    async def _stage_map(
        self, handover_ids: list
    ) -> dict:
        if not handover_ids:
            return {}
        result = await self._session.execute(
            select(
                HandoverStage.handover_id,
                HandoverStage.stage,
                HandoverStage.status,
            ).where(HandoverStage.handover_id.in_(handover_ids))
        )
        stages: dict = {}
        for handover_id, stage, status in result.all():
            stages.setdefault(handover_id, []).append((str(stage), str(status)))
        return stages

    async def _missing_parts(
        self, rows: list[dict], stage_rows: dict
    ) -> list[HandoverMissingPartOut]:
        counts: dict[str, int] = {}
        for row in rows:
            if row["status"] in _INACTIVE_STATUSES:
                continue
            for stage, status in stage_rows.get(row["id"], ()):
                if status == StageStatus.PASSED.value:
                    continue
                counts[stage] = counts.get(stage, 0) + 1
        ordered = sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )[:6]
        return [
            HandoverMissingPartOut(
                stage=stage,
                title=_operation_title(stage),
                count=count,
            )
            for stage, count in ordered
        ]

    def _per_day(self, rows: list[dict], period: str) -> list[HandoverPerDayOut]:
        day_count = 1 if period == "today" else 7 if period == "7d" else 30
        today = as_utc(self._now).date()
        days = [today - timedelta(days=offset) for offset in range(day_count - 1, -1, -1)]
        started = {day: 0 for day in days}
        completed = {day: 0 for day in days}
        for row in rows:
            created_day = _as_date(row["created_at"])
            if created_day in started:
                started[created_day] += 1
            if row["status"] == HandoverStatus.COMPLETED.value:
                closed_day = _as_date(row["closed_at"])
                if closed_day in completed:
                    completed[closed_day] += 1
        return [
            HandoverPerDayOut(
                day=day, started=started[day], completed=completed[day]
            )
            for day in days
        ]

    async def _activity(self) -> list[HandoverActivityOut]:
        result = await self._session.execute(
            select(
                Event.at,
                Event.type,
                Event.detail,
                Event.actor,
                Handover.id,
                Handover.device_serial,
                Handover.recipient_snipeit_name,
                Handover.recipient_snipeit_username,
                Handover.recipient_free_name,
            )
            .join(Handover, Handover.id == Event.handover_id)
            .where(
                Handover.kind == "handover",
                Handover.status != HandoverStatus.CANCELLED.value,
            )
            .order_by(Event.at.desc(), Event.id.desc())
            .limit(ACTIVITY_LIMIT)
        )
        items: list[HandoverActivityOut] = []
        for (
            at,
            event_type,
            detail,
            actor,
            case_id,
            serial,
            recipient_name,
            recipient_username,
            recipient_free,
        ) in result.all():
            recipient = recipient_name or recipient_username or recipient_free
            items.append(
                HandoverActivityOut(
                    time=at,
                    text=_activity_text(str(event_type), detail or {}, recipient),
                    case_id=case_id,
                    serial=serial,
                    engineer=actor,
                )
            )
        return items

    def _period_start(self, period: str) -> datetime | None:
        days = PERIOD_DAYS.get(period)
        if days is None:
            return None
        now = as_utc(self._now)
        if period == "today":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        return now - timedelta(days=days)

    def _row_stalled(self, row: dict) -> bool:
        if row["status"] not in _OPEN_STATUSES:
            return False
        cutoff = self._stall_cutoff()
        updated = as_utc(row["updated_at"])
        return cutoff is not None and updated is not None and updated < cutoff

    def _case_matches(
        self,
        handover: Handover,
        *,
        filter: str,
        period_start: datetime | None,
        stage: str | None,
        engineer: str | None,
    ) -> bool:
        status = handover.status
        open_case = status not in _INACTIVE_STATUSES
        conflict = company_conflict(
            handover.device_company, handover.recipient_company
        )
        if filter == "ready":
            return status == HandoverStatus.READY.value
        if filter == "complete":
            return status == HandoverStatus.COMPLETED.value and (
                period_start is None
                or (
                    as_utc(handover.closed_at) is not None
                    and as_utc(handover.closed_at) >= period_start
                )
            )
        if filter == "not_complete":
            return status in _OPEN_STATUSES
        if filter == "waiting_user":
            return open_case and handover.recipient_mode == PENDING_USER_MODE
        if filter == "stalled":
            return self._row_stalled(
                {
                    "status": status,
                    "updated_at": handover.updated_at,
                }
            )
        if filter == "warnings":
            completed_in_period = status == HandoverStatus.COMPLETED.value and (
                period_start is None
                or as_utc(handover.closed_at) >= period_start
            )
            return conflict and (open_case or completed_in_period)
        if filter == "missing":
            if not open_case or not stage:
                return False
            rows = {row.stage: row.status for row in handover.stages}
            return rows.get(stage) != StageStatus.PASSED.value
        if filter == "engineer":
            if not engineer:
                return False
            return (handover.engineer_name or "").casefold() == engineer.casefold()
        if filter == "attention":
            if not open_case:
                return False
            if status in _OPEN_STATUSES:
                return True
            return conflict or handover.recipient_mode == PENDING_USER_MODE
        return open_case

    # -- maintenance -------------------------------------------------------
    async def maintenance(
        self, *, today: date | None = None
    ) -> MaintenanceDashboardOut:
        """Return maintenance-only groups and open devices."""
        current_day = today or date.today()
        repo = MaintenanceRepository(self._session)
        needs = await repo.list_case_rows(state="with_it")
        at_vendor = await repo.list_case_rows(state="at_vendor")
        open_rows = [*needs, *at_vendor]

        def section(items: list[dict], include_average: bool = False) -> MaintenanceSectionOut:
            days = [
                days_in_maintenance(
                    item["received_date"], item["returned_date"], current_day
                )
                for item in items
            ]
            return MaintenanceSectionOut(
                total=len(items),
                by_model=_maintenance_groups(items, "model"),
                by_company=_maintenance_groups(items, "company"),
                by_vendor=_maintenance_groups(items, "vendor"),
                avg_days=round(sum(days) / len(days), 1) if include_average and days else 0,
            )

        devices = [
            MaintenanceDeviceOut(
                case_id=row["case_id"],
                serial=row["serial"],
                model=row["model"],
                company=row["company"],
                vendor=row["vendor"],
                vendor_id=row["vendor_id"],
                state=row["state"],
                days=days_in_maintenance(
                    row["received_date"], row["returned_date"], current_day
                ),
                reason=row["reason"],
            )
            for row in open_rows
        ]
        devices.sort(key=lambda item: (-item.days, item.serial))
        return MaintenanceDashboardOut(
            needs=section(needs),
            in_maintenance=section(at_vendor, include_average=True),
            devices=devices,
        )

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
                Handover.status.not_in(_INACTIVE_STATUSES),
                HandoverStage.status.not_in(
                    [StageStatus.PASSED.value, StageStatus.NOT_DONE.value]
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
        kind: str | None = None,
        q: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> HandoverRowListOut:
        service = HandoverService(self._session)
        handovers, total = await service.list(
            status=status,
            engineer=engineer,
            kind=kind,
            q=q,
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


def _maintenance_groups(
    rows: list[dict], key: str
) -> list[MaintenanceGroupOut]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key) or ("Not assigned" if key == "vendor" else "Unknown")
        counts[value] = counts.get(value, 0) + 1
    return [
        MaintenanceGroupOut(name=name, count=count)
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


# -- Round 2: handover dashboard helpers ------------------------------------

_OPEN_STATUSES = (
    HandoverStatus.DRAFT.value,
    HandoverStatus.IN_PROGRESS.value,
)
_KNOWN_COMPANIES = ("B.tech", "Nexta", "Mylo")
PENDING_USER_MODE = "pending_user"
PERIOD_DAYS: dict[str, int | None] = {
    "today": 1,
    "7d": 7,
    "30d": 30,
    "all": None,
}
ACTIVITY_LIMIT = 20
ATTENTION_LIMIT = 12
CASE_PANEL_LIMIT = 300


def _company_label(value: str | None) -> str:
    cleaned = (value or "").strip()
    return cleaned or "Unknown"


def _completed_in_period(row: dict, period_start: datetime | None) -> bool:
    if row["status"] != HandoverStatus.COMPLETED.value:
        return False
    if period_start is None:
        return True
    closed = as_utc(row["closed_at"])
    return closed is not None and closed >= period_start


def _hours_between(start: datetime | None, end: datetime | None) -> float | None:
    first = as_utc(start)
    last = as_utc(end)
    if first is None or last is None:
        return None
    return max(0.0, (last - first).total_seconds() / 3600.0)


def _as_date(value: datetime | None) -> date | None:
    moment = as_utc(value)
    return moment.date() if moment is not None else None


def _operation_title(stage: str) -> str:
    try:
        return operation_title(Operation(stage))
    except ValueError:
        return stage.replace("_", " ").capitalize()


def _by_company(
    rows: list[dict], period_start: datetime | None
) -> list[HandoverCompanyRowOut]:
    buckets: dict[str, dict[str, int]] = {
        name: {"ready": 0, "complete": 0, "not_complete": 0, "waiting_user": 0}
        for name in _KNOWN_COMPANIES
    }
    for row in rows:
        label = _company_label(row["device_company"])
        bucket = buckets.setdefault(
            label,
            {"ready": 0, "complete": 0, "not_complete": 0, "waiting_user": 0},
        )
        open_case = row["status"] not in _INACTIVE_STATUSES
        if row["status"] == HandoverStatus.READY.value:
            bucket["ready"] += 1
        if _completed_in_period(row, period_start):
            bucket["complete"] += 1
        if row["status"] in _OPEN_STATUSES:
            bucket["not_complete"] += 1
        if open_case and row["recipient_mode"] == PENDING_USER_MODE:
            bucket["waiting_user"] += 1
    ordered = [name for name in _KNOWN_COMPANIES if name in buckets]
    ordered.extend(
        sorted(name for name in buckets if name not in _KNOWN_COMPANIES)
    )
    return [
        HandoverCompanyRowOut(company=name, **buckets[name])
        for name in ordered
    ]


def _ready_by_model(rows: list[dict]) -> list[ReadyModelOut]:
    models: dict[str, dict[str, int]] = {}
    for row in rows:
        if row["status"] != HandoverStatus.READY.value:
            continue
        model = (row["device_model"] or "Unknown").strip() or "Unknown"
        company = _company_label(row["device_company"])
        split = models.setdefault(model, {})
        split[company] = split.get(company, 0) + 1
    ordered = sorted(
        models.items(),
        key=lambda item: (-sum(item[1].values()), item[0]),
    )[:8]
    return [
        ReadyModelOut(
            model=model,
            total=sum(split.values()),
            by_company=[
                ReadyModelCompanyOut(company=company, count=count)
                for company, count in sorted(
                    split.items(), key=lambda item: (-item[1], item[0])
                )
            ],
        )
        for model, split in ordered
    ]


def _by_engineer(
    rows: list[dict], period_start: datetime | None
) -> list[HandoverEngineerOut]:
    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        name = (row["engineer_name"] or "").strip() or "Unknown"
        bucket = buckets.setdefault(
            name, {"open": 0, "completed_in_period": 0}
        )
        if row["status"] not in _INACTIVE_STATUSES:
            bucket["open"] += 1
        if _completed_in_period(row, period_start):
            bucket["completed_in_period"] += 1
    return [
        HandoverEngineerOut(name=name, **counts)
        for name, counts in sorted(
            buckets.items(),
            key=lambda item: (
                -item[1]["open"],
                -item[1]["completed_in_period"],
                item[0],
            ),
        )
    ]


def _attention(
    rows: list[dict], stage_rows: dict, now: datetime
) -> list[HandoverAttentionOut]:
    current = as_utc(now)
    items: list[tuple[int, float, HandoverAttentionOut]] = []
    for row in rows:
        if row["status"] in _INACTIVE_STATUSES:
            continue
        conflict = company_conflict(
            row["device_company"], row["recipient_company"]
        )
        pending = row["recipient_mode"] == PENDING_USER_MODE
        if row["status"] not in _OPEN_STATUSES and not conflict and not pending:
            continue
        age_hours = _hours_between(row["created_at"], current) or 0.0
        days = max(1, int(age_hours // 24))
        failed_stage = next(
            (
                stage
                for stage, status in stage_rows.get(row["id"], ())
                if status == StageStatus.FAILED.value
                and stage in {operation.value for operation in HANDOVER_OPERATIONS}
            ),
            None,
        )
        stage: str | None = None
        if failed_stage is not None:
            priority = 0
            stage = failed_stage
            reason = f"{_operation_title(failed_stage)} missing"
        elif pending:
            priority = 1
            reason = f"Waiting user {days} days"
        elif row["status"] in _OPEN_STATUSES and _row_is_stalled(row, current):
            priority = 2
            reason = f"Stale {days} days"
        elif conflict:
            priority = 3
            reason = "Company differs"
        else:
            continue
        items.append(
            (
                priority,
                age_hours,
                HandoverAttentionOut(
                    id=row["id"],
                    serial=row["device_serial"],
                    model=row["device_model"],
                    company=row["device_company"],
                    recipient=(
                        row["recipient_snipeit_name"]
                        or row["recipient_snipeit_username"]
                        or row["recipient_free_name"]
                    ),
                    reason=reason,
                    age_hours=round(age_hours, 1),
                    filter="attention",
                    stage=stage,
                ),
            )
        )
    items.sort(key=lambda item: (item[0], -item[1]))
    return [item[2] for item in items[:ATTENTION_LIMIT]]


def _row_is_stalled(row: dict, now: datetime) -> bool:
    if config.STALL_HOURS <= 0:
        return False
    updated = as_utc(row["updated_at"])
    return updated is not None and updated < now - timedelta(
        hours=config.STALL_HOURS
    )


def _activity_text(
    event_type: str, detail: dict, recipient: str | None
) -> str:
    outcome = detail.get("outcome")
    if event_type == "checkout_attempt":
        if outcome == "passed":
            return f"Checked out to {recipient}" if recipient else "Checked out"
        return "Checkout failed"
    if event_type == "operation_recorded":
        operation = str(detail.get("operation") or "")
        if outcome != "passed":
            return f"{_operation_title(operation)} {outcome or 'not done'}"
        labels = {
            "checkout": f"Checked out to {recipient}" if recipient else "Checked out",
            "recipient_check": "Recipient confirmed",
            "recipient_items": "Items reviewed",
            "document_scanned": "Paper attached",
            "document_pushed": "Paper attached",
            "device_status": "Status applied",
            "agent_report": "Device report",
            "software_check": "Software checked",
            "report_printed": "Form printed",
        }
        return labels.get(operation, f"{_operation_title(operation)} done")
    if event_type == "recipient_changed":
        name = detail.get("new_name")
        return f"Recipient: {name}" if name else "Recipient changed"
    if event_type == "company_mismatch_warning":
        return "Company warning"
    if event_type == "pending_user_found":
        user = detail.get("username") or detail.get("name")
        return f"User found: {user}" if user else "User found"
    if event_type == "document_uploaded":
        return "Paper attached"
    if event_type == "handover_created":
        return "Case created"
    if event_type == "handover_cancelled":
        return "Cancelled"
    if event_type == "case_closed_with_gaps":
        return "Not complete"
    if event_type == "case_reopened":
        return "Reopened"
    return event_type.replace("_", " ").capitalize()


def _created_filters(
    created_from: datetime | None, created_to: datetime | None
) -> list:
    filters = []
    if created_from is not None:
        filters.append(Handover.created_at >= created_from)
    if created_to is not None:
        filters.append(Handover.created_at <= created_to)
    return filters
