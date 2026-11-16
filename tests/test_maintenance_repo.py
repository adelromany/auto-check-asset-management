"""Tests for MaintenanceRepository and governed lists (Part D)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.handover import Handover
from app.db.models.maintenance import MaintenanceDestination, MaintenanceInfo
from app.repositories.maintenance import MaintenanceRepository


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await engine.dispose()


async def test_ensure_destination_and_vendor(session: AsyncSession) -> None:
    repo = MaintenanceRepository(session)
    v1 = await repo.ensure_vendor("FixTech")
    assert v1.id is not None
    assert v1.name == "FixTech"
    assert v1.name_key == "fixtech"

    # Case-insensitive reuse
    v2 = await repo.ensure_vendor("fixtech")
    assert v2.id == v1.id

    vendors = await repo.list_vendors()
    assert len(vendors) == 1
    assert vendors[0].name == "FixTech"


async def test_ensure_diagnosis_category(session: AsyncSession) -> None:
    repo = MaintenanceRepository(session)
    c1 = await repo.ensure_diagnosis_category("Screen")
    assert c1.name == "Screen"
    assert c1.name_key == "screen"

    c2 = await repo.ensure_diagnosis_category("SCREEN")
    assert c2.id == c1.id


async def test_apply_fields_and_create_info(session: AsyncSession) -> None:
    repo = MaintenanceRepository(session)
    info = await repo.create_info(
        {
            "reported_issue": "Broken screen",
            "destination": "FixTech",
            "condition_notes": "Scratches on lid",
        }
    )
    assert info.reported_issue == "Broken screen"
    assert info.destination_id is not None
    assert info.condition_notes == "Scratches on lid"

    changed = await repo.apply_fields(
        info,
        {
            "reported_issue": "Broken screen",  # unchanged
            "reference": "RMA-9999",  # new
        },
    )
    assert changed == ["reference"]
    assert info.reference == "RMA-9999"


async def test_seed_defaults(session: AsyncSession) -> None:
    repo = MaintenanceRepository(session)
    await repo.seed_defaults()

    vendors = await repo.list_vendors()
    vendor_names = {v.name for v in vendors}
    assert "FixTech" in vendor_names

    categories = await repo.list_diagnosis_categories()
    cat_names = {c.name for c in categories}
    assert "Screen" in cat_names
    assert "Battery" in cat_names
    assert "Other" in cat_names
