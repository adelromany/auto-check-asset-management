"""Data access for maintenance cases and their governed lists (ARC-02).

Case rows stay in ``handovers`` (rename deferred, D-69); this module owns the
``maintenance_info`` row and the governed lists (vendors/destinations, categories).
Services own transactions; this module reads, creates and flushes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.maintenance import (
    DiagnosisCategory,
    MaintenanceDestination,
    MaintenanceInfo,
    MaintenanceVendor,
)

_FIELD_NAMES: tuple[str, ...] = (
    "reported_issue",
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
    "Battery",
    "Keyboard",
    "Motherboard",
    "Software",
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

    async def list_vendors(self) -> list[MaintenanceVendor]:
        """Semantic alias for list_destinations."""
        return await self.list_destinations()

    async def list_diagnosis_categories(self) -> list[DiagnosisCategory]:
        result = await self._session.execute(
            select(DiagnosisCategory)
            .where(DiagnosisCategory.active.is_(True))
            .order_by(DiagnosisCategory.name)
        )
        return list(result.scalars().all())

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
