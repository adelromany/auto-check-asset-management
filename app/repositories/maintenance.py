"""Data access for maintenance cases and their governed lists (ARC-02).

Case rows stay in ``handovers`` (rename deferred, D-69); this module owns the
``maintenance_info`` row and the governed lists (vendors/destinations, categories).
Services own transactions; this module reads, creates and flushes.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, and_, case, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.handover import Handover, HandoverStage
from app.db.models.maintenance import (
    DiagnosisCategory,
    MaintenanceDestination,
    MaintenanceInfo,
    MaintenanceVendor,
)
from app.domain.maintenance_rules import (
    MaintenanceState,
    derive_maintenance_state,
    is_overdue,
)

def case_state_filter(state: MaintenanceState | str) -> ColumnElement[bool]:
    """Return the SQL predicate matching one derived maintenance state.

    Matches ``derive_maintenance_state``:
    - ``returned``: ``returned`` stage passed
    - ``at_vendor``: ``sent_out`` stage passed and ``returned`` not passed
    - ``with_it``: neither ``sent_out`` nor ``returned`` passed
    Rows without any ``handover_stages`` (legacy test fixtures) fall back to
    ``Handover.maintenance_state``.
    """
    target = MaintenanceState(state).value
    has_stages = exists(
        select(HandoverStage.id).where(HandoverStage.handover_id == Handover.id)
    )
    sent_passed = exists(
        select(HandoverStage.id).where(
            HandoverStage.handover_id == Handover.id,
            HandoverStage.stage == "sent_out",
            HandoverStage.status == "passed",
        )
    )
    returned_passed = exists(
        select(HandoverStage.id).where(
            HandoverStage.handover_id == Handover.id,
            HandoverStage.stage == "returned",
            HandoverStage.status == "passed",
        )
    )
    if target == MaintenanceState.RETURNED.value:
        stage_pred: ColumnElement[bool] = returned_passed
        fallback_pred: ColumnElement[bool] = Handover.maintenance_state == target
    elif target == MaintenanceState.AT_VENDOR.value:
        stage_pred = and_(sent_passed, ~returned_passed)
        fallback_pred = Handover.maintenance_state == target
    else:
        stage_pred = and_(~sent_passed, ~returned_passed)
        fallback_pred = or_(
            Handover.maintenance_state.is_(None),
            Handover.maintenance_state == MaintenanceState.WITH_IT.value,
        )
    return or_(
        and_(has_stages, stage_pred),
        and_(~has_stages, fallback_pred),
    )


_FIELD_NAMES: tuple[str, ...] = (
    "reported_issue",
    "priority",
    "condition_notes",
    "accessories",
    "diagnosis_category",
    "diagnosis_note",
    "sent_date",
    "sent_by",
    "reference",
    "expected_return_date",
    "returned_date",
    "outcome",
    "outcome_note",
    "cost",
    "warranty",
)

DEFAULT_VENDORS: tuple[str, ...] = ("FixTech",)
DEFAULT_CATEGORIES: tuple[str, ...] = (
    "Screen",
    "Keyboard",
    "Battery",
    "Charger / power",
    "Won't power on",
    "Overheating",
    "Slow",
    "Disk",
    "RAM",
    "Motherboard",
    "Network",
    "Ports",
    "Speaker / mic / webcam",
    "Hinge / body",
    "Liquid damage",
    "OS / software",
    "BIOS / boot",
    "Other",
)


class MaintenanceRepository:
    """Data access for maintenance fields and the governed list values."""

    def __init__(self, session: AsyncSession):
        self._session = session

    # -- governed lists ---------------------------------------------------
    async def list_destinations(self) -> list[MaintenanceDestination]:
        result = await self._session.execute(
            select(MaintenanceDestination)
            .where(MaintenanceDestination.active.is_(True))
            .order_by(MaintenanceDestination.name)
        )
        return list(result.scalars().all())

    async def list_vendors(self, *, include_inactive: bool = False) -> list[MaintenanceVendor]:
        statement = select(MaintenanceDestination)
        if not include_inactive:
            statement = statement.where(MaintenanceDestination.active.is_(True))
        result = await self._session.execute(statement.order_by(MaintenanceDestination.name))
        return list(result.scalars().all())

    async def get_vendor(self, vendor_id: int) -> MaintenanceDestination | None:
        return await self._session.get(MaintenanceDestination, vendor_id)

    async def find_vendor(self, name: str) -> MaintenanceDestination | None:
        return await self._session.scalar(
            select(MaintenanceDestination).where(
                func.lower(MaintenanceDestination.name) == name.strip().lower()
            )
        )

    async def vendor_stats(self) -> dict[int, dict[str, float | int | None]]:
        sent = MaintenanceInfo.sent_date.is_not(None)
        at_vendor = case_state_filter(MaintenanceState.AT_VENDOR)
        dialect = self._session.bind.dialect.name if self._session.bind else "sqlite"
        if dialect == "sqlite":
            elapsed_days = func.julianday(MaintenanceInfo.returned_date) - func.julianday(MaintenanceInfo.sent_date)
        else:
            elapsed_days = func.extract("epoch", MaintenanceInfo.returned_date - MaintenanceInfo.sent_date) / 86400
        average_days = func.avg(
            case(
                (and_(MaintenanceInfo.sent_date.is_not(None), MaintenanceInfo.returned_date.is_not(None)), elapsed_days),
                else_=None,
            )
        )
        statement = (
            select(
                MaintenanceDestination.id,
                func.sum(case((and_(sent, at_vendor), 1), else_=0)),
                func.sum(case((sent, 1), else_=0)),
                func.sum(case((MaintenanceInfo.returned_date.is_not(None), 1), else_=0)),
                average_days,
                func.count(MaintenanceInfo.handover_id),
            )
            .outerjoin(MaintenanceInfo, MaintenanceInfo.destination_id == MaintenanceDestination.id)
            .outerjoin(Handover, Handover.id == MaintenanceInfo.handover_id)
            .group_by(MaintenanceDestination.id)
        )
        rows = (await self._session.execute(statement)).all()
        overdue_rows = (
            await self._session.execute(
                select(
                    MaintenanceInfo.destination_id,
                    MaintenanceInfo.sent_date,
                    MaintenanceInfo.expected_return_date,
                )
                .join(Handover, Handover.id == MaintenanceInfo.handover_id)
                .where(
                    MaintenanceInfo.destination_id.is_not(None),
                    case_state_filter(MaintenanceState.AT_VENDOR),
                )
            )
        ).all()
        overdue_by_vendor: dict[int, int] = {}
        for vendor_id, sent_date, expected_return_date in overdue_rows:
            if is_overdue(
                sent_date=sent_date,
                expected_return_date=expected_return_date,
                today=date.today(),
                returned=False,
            ):
                overdue_by_vendor[vendor_id] = overdue_by_vendor.get(vendor_id, 0) + 1
        return {
            vendor_id: {
                "at_vendor_now": int(at_now or 0),
                "total_sent": int(total or 0),
                "returned_total": int(returned or 0),
                "overdue_now": overdue_by_vendor.get(vendor_id, 0),
                "avg_days": float(avg) if avg is not None else None,
                "can_delete": referenced == 0,
            }
            for vendor_id, at_now, total, returned, avg, referenced in rows
        }

    async def create_vendor(self, values: Mapping[str, Any]) -> MaintenanceDestination:
        name = str(values["name"]).strip()
        vendor = MaintenanceDestination(name=name, name_key=name.casefold())
        for key in ("contact_name", "phone", "email", "notes"):
            setattr(vendor, key, values.get(key))
        self._session.add(vendor)
        await self._session.flush()
        return vendor

    async def update_vendor(self, vendor: MaintenanceDestination, values: Mapping[str, Any]) -> None:
        for key, value in values.items():
            if key == "is_active":
                vendor.active = value
            elif key == "name" and value is not None:
                vendor.name = value.strip()
                vendor.name_key = vendor.name.casefold()
            else:
                setattr(vendor, key, value)
        await self._session.flush()

    async def vendor_is_referenced(self, vendor_id: int) -> bool:
        return bool(await self._session.scalar(
            select(exists().where(MaintenanceInfo.destination_id == vendor_id))
        ))

    async def delete_vendor(self, vendor: MaintenanceDestination) -> None:
        await self._session.delete(vendor)
        await self._session.flush()

    async def list_diagnosis_categories(self) -> list[DiagnosisCategory]:
        result = await self._session.execute(
            select(DiagnosisCategory).where(DiagnosisCategory.active.is_(True))
        )
        categories = list(result.scalars().all())
        order = {name.casefold(): index for index, name in enumerate(DEFAULT_CATEGORIES)}
        categories.sort(
            key=lambda item: (
                1 if item.name_key == "other" else 0,
                order.get(item.name_key, len(order)),
                item.name.casefold(),
            )
        )
        return categories

    async def get_diagnosis_category(self, category_id: int) -> DiagnosisCategory | None:
        return await self._session.scalar(
            select(DiagnosisCategory).where(
                DiagnosisCategory.id == category_id,
                DiagnosisCategory.active.is_(True),
            )
        )

    async def get_destination(self, destination_id: int) -> MaintenanceDestination | None:
        return await self._session.scalar(
            select(MaintenanceDestination).where(
                MaintenanceDestination.id == destination_id,
                MaintenanceDestination.active.is_(True),
            )
        )

    async def ensure_destination(self, name: str) -> MaintenanceDestination:
        """Return the case-insensitive list row, creating it when new."""
        cleaned = (name or "").strip()
        key = cleaned.casefold()
        existing = await self._session.scalar(
            select(MaintenanceDestination).where(
                MaintenanceDestination.name_key == key
            )
        )
        if existing is not None:
            if not existing.active:
                existing.active = True
                await self._session.flush()
            return existing
        destination = MaintenanceDestination(name=cleaned, name_key=key)
        try:
            async with self._session.begin_nested():
                self._session.add(destination)
                await self._session.flush()
        except IntegrityError:
            # A concurrent request created it first; reuse that row.
            destination = await self._session.scalar(
                select(MaintenanceDestination).where(
                    MaintenanceDestination.name_key == key
                )
            )
            assert destination is not None
        return destination

    async def ensure_vendor(self, name: str) -> MaintenanceVendor:
        """Semantic alias for ensure_destination."""
        return await self.ensure_destination(name)

    async def ensure_diagnosis_category(self, name: str) -> DiagnosisCategory:
        cleaned = (name or "").strip()
        key = cleaned.casefold()
        existing = await self._session.scalar(
            select(DiagnosisCategory).where(DiagnosisCategory.name_key == key)
        )
        if existing is not None:
            if not existing.active:
                existing.active = True
                await self._session.flush()
            return existing
        category = DiagnosisCategory(name=cleaned, name_key=key)
        try:
            async with self._session.begin_nested():
                self._session.add(category)
                await self._session.flush()
        except IntegrityError:
            category = await self._session.scalar(
                select(DiagnosisCategory).where(DiagnosisCategory.name_key == key)
            )
            assert category is not None
        return category

    async def seed_defaults(self) -> None:
        """Seed default vendor ('FixTech') and common issue categories."""
        for v in DEFAULT_VENDORS:
            await self.ensure_vendor(v)
        for c in DEFAULT_CATEGORIES:
            await self.ensure_diagnosis_category(c)
        await self._session.flush()

    # -- typed fields -----------------------------------------------------
    async def create_info(
        self, values: Mapping[str, Any]
    ) -> MaintenanceInfo:
        info = MaintenanceInfo()
        await self.apply_fields(info, values)
        return info

    async def apply_fields(
        self,
        info: MaintenanceInfo,
        values: Mapping[str, Any],
    ) -> list[str]:
        """Copy the supplied fields; return the names that actually changed.

        ``None`` is a deliberate clear for an update. A key that is absent
        stays as it was, which is what a partial action payload means.
        """
        changed: list[str] = []
        for name in _FIELD_NAMES:
            if name not in values:
                continue
            value = values[name]
            cleaned = value.strip() if isinstance(value, str) else value
            if cleaned == "":
                cleaned = None
            if getattr(info, name) != cleaned:
                setattr(info, name, cleaned)
                changed.append(name)

        target_vendor = values.get("vendor") or values.get("destination")
        if target_vendor is not None or "vendor" in values or "destination" in values:
            name = target_vendor.strip() if isinstance(target_vendor, str) else target_vendor
            destination_id = None
            destination = None
            if name:
                destination = await self.ensure_destination(name)
                destination_id = destination.id
            if info.destination_id != destination_id:
                info.destination_id = destination_id
                info.destination = destination
                changed.append("destination")

        if "diagnosis_category" in values and info.diagnosis_category:
            await self.ensure_diagnosis_category(info.diagnosis_category)

        return changed

    async def list_case_rows(
        self,
        *,
        state: str | None = None,
        company: str | None = None,
        model: str | None = None,
        vendor_id: int | None = None,
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        statement = (
            select(Handover, MaintenanceInfo)
            .outerjoin(MaintenanceInfo, MaintenanceInfo.handover_id == Handover.id)
            .options(selectinload(Handover.stages))
            .where(Handover.kind == "maintenance")
        )
        if state:
            statement = statement.where(case_state_filter(state))
        if company:
            statement = statement.where(Handover.device_company == company)
        if model:
            statement = statement.where(Handover.device_model == model)
        if vendor_id is not None:
            statement = statement.where(MaintenanceInfo.destination_id == vendor_id)
        if q:
            statement = statement.where(Handover.device_serial.ilike(f"%{q.strip()}%"))
        result = await self._session.execute(
            statement.order_by(Handover.created_at.desc(), Handover.id)
        )
        return [self._case_row(handover, info) for handover, info in result.all()]

    async def all_case_rows(self) -> list[dict[str, Any]]:
        return await self.list_case_rows()

    @staticmethod
    def _case_row(
        handover: Handover, info: MaintenanceInfo | None
    ) -> dict[str, Any]:
        vendor = info.destination.name if info is not None and info.destination else None
        if handover.stages:
            derived_state = derive_maintenance_state(
                {s.stage: s.status for s in handover.stages}
            ).value
        else:
            derived_state = handover.maintenance_state or MaintenanceState.WITH_IT.value
        return {
            "case_id": handover.id,
            "serial": handover.device_serial,
            "model": handover.device_model or "Unknown",
            "company": handover.device_company or "Unknown",
            "vendor": vendor,
            "vendor_id": info.destination_id if info is not None else None,
            "planned_vendor": vendor,
            "assigned_to": handover.recipient_snipeit_name,
            "snipeit_status": handover.snipeit_status_name,
            "stages": [
                {"stage": stage.stage, "status": stage.status}
                for stage in handover.stages
            ],
            "state": derived_state,
            "received_date": info.received_date if info is not None else None,
            "sent_date": info.sent_date if info is not None else None,
            "returned_date": info.returned_date if info is not None else None,
            "reason": (
                (info.reason_text or info.diagnosis_category)
                if info is not None
                else None
            ),
        }

