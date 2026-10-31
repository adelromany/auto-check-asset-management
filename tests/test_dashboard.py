"""Phase 7: dashboard aggregates, table rows and server-rendered pages."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401  (registers every table on Base.metadata)
import app.dependencies
import app.main
from app import config
from app.db.base import Base
from app.db.models.handover import Handover, HandoverStage
from app.domain.stages import STAGE_ORDER, Stage, StageStatus
from app.services.sessions import SessionStore

ENGINEER_A = ("Engineer A", "engineer.a@example.com")
ENGINEER_B = ("Engineer B", "engineer.b@example.com")
ALL_PASSED = tuple(STAGE_ORDER)


@dataclass
class DashboardHarness:
    app: FastAPI
    client: httpx.AsyncClient
    factory: async_sessionmaker


def _stages(*, passed=(), blocked=(), failed=()) -> list[HandoverStage]:
    rows = []
    for stage in STAGE_ORDER:
        status = StageStatus.PENDING.value
        if stage in passed:
            status = StageStatus.PASSED.value
        elif stage in blocked:
            status = StageStatus.BLOCKED.value
        elif stage in failed:
            status = StageStatus.FAILED.value
        rows.append(HandoverStage(stage=stage.value, status=status))
    return rows


def _handover(
    *,
    serial: str,
    engineer: tuple[str, str],
    status: str,
    created: datetime,
    closed: datetime | None = None,
    stages: list[HandoverStage] | None = None,
    reported: str = "alice",
    confirmed: str = "alice",
) -> Handover:
    return Handover(
        status=status,
        engineer_email=engineer[1],
        engineer_name=engineer[0],
        device_serial=serial,
        recipient_reported_username=reported,
        recipient_snipeit_username=confirmed,
        created_at=created,
        closed_at=closed,
        stages=stages if stages is not None else _stages(),
    )


async def _seed(factory: async_sessionmaker) -> None:
    """One handover in every derived status, two engineers, two completions."""
    async with factory() as session:
        session.add_all(
            [
                _handover(
                    serial="SN-COMP-1",
                    engineer=ENGINEER_A,
                    status="completed",
                    created=datetime(2026, 10, 1, 9, 0),
                    closed=datetime(2026, 10, 1, 10, 0),
                    stages=_stages(passed=ALL_PASSED),
                ),
                _handover(
                    serial="SN-INPROG",
                    engineer=ENGINEER_A,
                    status="in_progress",
                    created=datetime(2026, 10, 5, 9, 0),
                    stages=_stages(
                        passed=(
                            STAGE_ORDER[0],
                            STAGE_ORDER[1],
                            STAGE_ORDER[2],
                        )
                    ),
                ),
                _handover(
                    serial="SN-STALLED",
                    engineer=ENGINEER_B,
                    status="stalled",
                    created=datetime(2026, 10, 10, 9, 0),
                    stages=_stages(
                        passed=(
                            STAGE_ORDER[0],
                            STAGE_ORDER[1],
                            STAGE_ORDER[2],
                            Stage.SOFTWARE_CHECK,
                        ),
                        blocked=(Stage.RECIPIENT_CHECK,),
                    ),
                ),
                _handover(
                    serial="SN-DRAFT",
                    engineer=ENGINEER_B,
                    status="draft",
                    created=datetime(2026, 10, 15, 9, 0),
                ),
                _handover(
                    serial="SN-CANCEL",
                    engineer=ENGINEER_A,
                    status="cancelled",
                    created=datetime(2026, 10, 20, 9, 0),
                ),
                _handover(
                    serial="SN-COMP-2",
                    engineer=ENGINEER_B,
                    status="completed",
                    created=datetime(2026, 10, 22, 9, 0),
                    closed=datetime(2026, 10, 22, 11, 0),
                    stages=_stages(passed=ALL_PASSED),
                ),
            ]
        )
        await session.commit()


@pytest_asyncio.fixture()
async def dashboard(monkeypatch):
    # Pages check the session only when SSO is on; keep it off by default and
    # let the login tests turn it back on.
    monkeypatch.setattr(config, "SSO_ENABLED", False)

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _seed(factory)

    application = app.main.create_app()
    store = SessionStore(ttl_seconds=600)

    async def override_session():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[app.dependencies.get_session] = override_session
    application.dependency_overrides[app.dependencies.current_user] = lambda: {
        "name": ENGINEER_A[0],
        "email": ENGINEER_A[1],
    }
    application.dependency_overrides[app.dependencies.get_store] = lambda: store

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        csrf = await client.get("/api/me")
        client.headers["X-CSRF-Token"] = csrf.headers["X-CSRF-Token"]
        yield DashboardHarness(app=application, client=client, factory=factory)

    await engine.dispose()


async def _add(harness: DashboardHarness, **kwargs) -> None:
    async with harness.factory() as session:
        session.add(_handover(**kwargs))
        await session.commit()


async def _id_for(harness: DashboardHarness, serial: str) -> uuid.UUID:
    async with harness.factory() as session:
        value = await session.scalar(
            select(Handover.id).where(Handover.device_serial == serial)
        )
    assert value is not None
    return value


# -- summary ----------------------------------------------------------------


async def test_summary_counts_every_status(dashboard: DashboardHarness) -> None:
    response = await dashboard.client.get("/api/dashboard/handovers/summary")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 6
    assert body["completed"] == 2
    assert body["by_status"] == {
        "draft": 1,
        "in_progress": 1,
        "stalled": 1,
        "completed": 2,
        "cancelled": 1,
    }


async def test_summary_per_stage_matrix(dashboard: DashboardHarness) -> None:
    body = (
        await dashboard.client.get("/api/dashboard/handovers/summary")
    ).json()

    assert set(body["stages"]) == {stage.value for stage in STAGE_ORDER}
    assert body["stages"]["device_prepared"] == {
        "passed": 4,
        "pending": 2,
        "blocked": 0,
        "failed": 0,
        "skipped": 0,
    }
    assert body["stages"]["recipient_check"] == {
        "passed": 2,
        "pending": 3,
        "blocked": 1,
        "failed": 0,
        "skipped": 0,
    }


async def test_summary_average_time_to_complete(
    dashboard: DashboardHarness,
) -> None:
    body = (
        await dashboard.client.get("/api/dashboard/handovers/summary")
    ).json()

    # 1 hour and 2 hours -> 5400 seconds, computed by the database.
    assert body["average_time_to_complete_seconds"] == 5400.0


async def test_summary_per_engineer_counts(dashboard: DashboardHarness) -> None:
    body = (
        await dashboard.client.get("/api/dashboard/handovers/summary")
    ).json()

    engineers = {item["email"]: item for item in body["by_engineer"]}
    assert engineers[ENGINEER_A[1]] == {
        "email": ENGINEER_A[1],
        "name": ENGINEER_A[0],
        "total": 3,
        "completed": 1,
    }
    assert engineers[ENGINEER_B[1]]["total"] == 3
    assert engineers[ENGINEER_B[1]]["completed"] == 1


async def test_summary_top_missing_steps_ignores_closed_cases(
    dashboard: DashboardHarness,
) -> None:
    body = (
        await dashboard.client.get("/api/dashboard/handovers/summary")
    ).json()

    top = body["top_missing_steps"]
    assert len(top) == 5
    counts = {item["stage"]: item["count"] for item in top}
    # Active cases only: two in-progress/stalled plus one draft.
    assert counts["recipient_check"] == 3
    assert counts["checkout"] == 3
    assert all(item["count"] >= 1 for item in top)


async def test_summary_date_filter_includes_the_whole_to_day(
    dashboard: DashboardHarness,
) -> None:
    response = await dashboard.client.get(
        "/api/dashboard/handovers/summary?from=2026-10-10&to=2026-10-15"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert body["by_status"]["stalled"] == 1
    assert body["by_status"]["draft"] == 1
    assert body["completed"] == 0


async def test_summary_rejects_an_invalid_date(
    dashboard: DashboardHarness,
) -> None:
    response = await dashboard.client.get(
        "/api/dashboard/handovers/summary?from=not-a-date"
    )

    assert response.status_code == 422


async def test_summary_requires_authentication(
    dashboard: DashboardHarness, monkeypatch
) -> None:
    dashboard.app.dependency_overrides.pop(app.dependencies.current_user, None)
    monkeypatch.setattr(config, "SSO_ENABLED", True)

    response = await dashboard.client.get("/api/dashboard/handovers/summary")

    assert response.status_code == 401


# -- table rows -------------------------------------------------------------


async def test_rows_include_progress_and_missing_steps(
    dashboard: DashboardHarness,
) -> None:
    response = await dashboard.client.get(
        "/api/dashboard/handovers?status=stalled"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["handover"]["device_serial"] == "SN-STALLED"
    assert len(row["stages"]) == 10
    assert [item["status"] for item in row["stages"]].count("blocked") == 1
    assert row["missing_steps"][0]["stage"] == "recipient_check"
    assert row["missing_steps"][0]["status"] == "blocked"


async def test_rows_filter_by_engineer_and_range(
    dashboard: DashboardHarness,
) -> None:
    response = await dashboard.client.get(
        "/api/dashboard/handovers",
        params={
            "engineer": ENGINEER_B[1],
            "from": "2026-10-01",
            "to": "2026-10-31",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert {item["handover"]["device_serial"] for item in body["items"]} == {
        "SN-STALLED",
        "SN-DRAFT",
        "SN-COMP-2",
    }


# -- pages ------------------------------------------------------------------


async def test_handovers_page_renders_seeded_data(
    dashboard: DashboardHarness,
) -> None:
    response = await dashboard.client.get("/handovers")

    assert response.status_code == 200, response.text
    body = response.text
    assert "Handovers" in body
    assert "SN-COMP-1" in body
    assert "SN-STALLED" in body
    assert "Completed" in body
    assert "Recipient check" in body


async def test_handover_page_renders_the_case(
    dashboard: DashboardHarness,
) -> None:
    handover_id = await _id_for(dashboard, "SN-STALLED")

    response = await dashboard.client.get(f"/handovers/{handover_id}")

    assert response.status_code == 200, response.text
    body = response.text
    assert "SN-STALLED" in body
    assert "Recipient check" in body
    assert "Blocked" in body
    assert "Events" in body
    assert "alice" in body


async def test_pages_escape_recipient_names(
    dashboard: DashboardHarness,
) -> None:
    payload = "<script>alert(1)</script>"
    await _add(
        dashboard,
        serial="SN-XSS",
        engineer=ENGINEER_A,
        status="draft",
        created=datetime(2026, 10, 25, 9, 0),
        reported=payload,
        confirmed=payload,
    )
    handover_id = await _id_for(dashboard, "SN-XSS")

    response = await dashboard.client.get(f"/handovers/{handover_id}")

    assert response.status_code == 200
    assert payload not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


async def test_pages_require_login(
    dashboard: DashboardHarness, monkeypatch
) -> None:
    monkeypatch.setattr(config, "SSO_ENABLED", True)

    listing = await dashboard.client.get("/handovers")
    detail = await dashboard.client.get(f"/handovers/{uuid.uuid4()}")

    assert listing.status_code == 307
    assert listing.headers["location"] == "/login"
    assert detail.status_code == 307
    assert detail.headers["location"] == "/login"


async def test_unknown_handover_page_is_404(
    dashboard: DashboardHarness,
) -> None:
    response = await dashboard.client.get(f"/handovers/{uuid.uuid4()}")

    assert response.status_code == 404
