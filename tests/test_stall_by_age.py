"""Fake-clock and database-side stalled-by-age behavior."""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app import config
from app.db.base import Base
from app.db.models.handover import Handover
from app.domain.handover_rules import StageState, derive_status
from app.domain.stages import STAGE_ORDER, HandoverStatus, Stage, StageStatus
from app.services.dashboard import DashboardService
from app.services.handovers import HandoverService


@pytest.mark.parametrize(
    ("updated_at", "hours", "expected"),
    [
        (datetime(2026, 10, 30, 12, tzinfo=timezone.utc), 24, HandoverStatus.DRAFT),
        (datetime(2026, 10, 30, 11, 59, 59, tzinfo=timezone.utc), 24, HandoverStatus.STALLED),
        (datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc), 0, HandoverStatus.DRAFT),
    ],
)
def test_age_status_boundary_and_disable(updated_at, hours, expected):
    states = [StageState(stage, StageStatus.PENDING) for stage in STAGE_ORDER]
    assert derive_status(
        states,
        updated_at=updated_at,
        now=datetime(2026, 10, 31, 12, tzinfo=timezone.utc),
        stall_hours=hours,
    ) is expected


def test_terminal_cases_never_stall_by_age():
    states = [StageState(stage, StageStatus.SKIPPED) for stage in STAGE_ORDER]
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = datetime(2026, 10, 31, tzinfo=timezone.utc)
    assert derive_status(states, updated_at=old, now=now, stall_hours=1) is HandoverStatus.COMPLETED
    assert derive_status(states, cancelled=True, updated_at=old, now=now, stall_hours=1) is HandoverStatus.CANCELLED


@pytest_asyncio.fixture()
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def test_dashboard_summary_and_status_filters_agree(session, monkeypatch):
    monkeypatch.setattr(config, "STALL_HOURS", 24)
    core = HandoverService(session)
    handover = await core.create(
        device_serial="AGE-1", engineer_email="engineer@example.test", engineer_name="Engineer"
    )
    fake_now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
    handover.updated_at = fake_now - timedelta(hours=25)
    await session.flush()

    dashboard = DashboardService(session, now=fake_now)
    summary = await dashboard.summary()
    stalled = await dashboard.rows(status="stalled")
    drafts = await dashboard.rows(status="draft")
    all_rows = await dashboard.rows()

    assert summary.by_status["stalled"] == 1
    assert summary.by_status["draft"] == 0
    assert stalled.total == 1
    assert stalled.items[0].handover.status == "stalled"
    assert drafts.total == 0
    assert all_rows.items[0].handover.status == "stalled"
