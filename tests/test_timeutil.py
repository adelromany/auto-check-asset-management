"""Timezone helper regression cases."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.models.handover import Handover
from app.domain.handover_rules import stalled_by_age
from app.domain.stages import HandoverStatus
from app.services.dashboard import DashboardService
from app.services.handovers import HandoverService

from app.domain.timeutil import as_utc


def test_as_utc_handles_naive_aware_and_none():
    naive = datetime(2026, 10, 31, 12, 0)
    assert as_utc(naive) == naive.replace(tzinfo=timezone.utc)
    plus_three = timezone(timedelta(hours=3))
    aware = datetime(2026, 10, 31, 15, 0, tzinfo=plus_three)
    assert as_utc(aware) == naive.replace(tzinfo=timezone.utc)
    assert as_utc(None) is None


@pytest.mark.asyncio
async def test_sqlite_readback_is_safe_for_age_and_dashboard_duration(tmp_path):
    path = tmp_path / "sqlite-datetime.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        handover = await HandoverService(session).create(
            device_serial="TIME-1",
            engineer_email="engineer@example.test",
            engineer_name="Engineer",
        )
        handover.status = HandoverStatus.COMPLETED.value
        handover.created_at = datetime(2026, 10, 31, 10, tzinfo=timezone.utc)
        handover.updated_at = datetime(2026, 10, 31, 11, tzinfo=timezone.utc)
        handover.closed_at = datetime(2026, 10, 31, 11, tzinfo=timezone.utc)
        handover_id = handover.id
        await session.commit()
        session.expire_all()
        loaded = await session.scalar(select(Handover).where(Handover.id == handover_id))

        assert loaded is not None
        assert loaded.updated_at.tzinfo is None
        assert stalled_by_age(
            loaded.updated_at,
            datetime(2026, 11, 1, 12, tzinfo=timezone.utc),
            24,
        )
        summary = await DashboardService(
            session, now=datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
        ).summary()
        assert summary.average_time_to_complete_seconds == 3600.0
    await engine.dispose()
