"""Phase 7: dashboard aggregates, table rows and server-rendered pages."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

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
from app.db.models.handover import Event, Handover, HandoverStage
from app.db.models.maintenance import MaintenanceDestination, MaintenanceInfo
from app.domain.stages import STAGE_ORDER, Stage, StageStatus
from app.services.sessions import SessionStore

ENGINEER_A = ("Engineer A", "engineer.a@example.com")
ENGINEER_B = ("Engineer B", "engineer.b@example.com")
ALL_PASSED = tuple(STAGE_ORDER)
NOW = datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class DashboardHarness:
    app: FastAPI
    client: httpx.AsyncClient
    factory: async_sessionmaker


def _stages(*, passed=(), not_done=(), failed=()) -> list[HandoverStage]:
    rows = []
    for stage in STAGE_ORDER:
        status = StageStatus.PENDING.value
        if stage in passed:
            status = StageStatus.PASSED.value
        elif stage in not_done:
            status = StageStatus.NOT_DONE.value
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
    updated: datetime | None = None,
    company: str | None = None,
    kind: str = "handover",
    recipient_mode: str | None = None,
    recipient_company: str | None = None,
) -> Handover:
    return Handover(
        status=status,
        kind=kind,
        device_company=company,
        recipient_mode=recipient_mode,
        recipient_company=recipient_company,
        engineer_email=engineer[1],
        engineer_name=engineer[0],
        device_serial=serial,
        recipient_reported_username=reported,
        recipient_snipeit_username=confirmed,
        created_at=created,
        updated_at=updated or NOW,
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
                    status="in_progress",
                    created=datetime(2026, 10, 10, 9, 0),
                    updated=NOW - timedelta(days=2),
                    stages=_stages(
                        passed=(
                            STAGE_ORDER[0],
                            STAGE_ORDER[1],
                            STAGE_ORDER[2],
                            Stage.SOFTWARE_CHECK,
                        ),
                        not_done=(Stage.RECIPIENT_CHECK,),
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


def test_vendor_averages_include_returned_devices() -> None:
    from app.routers.pages import _vendor_averages

    rows = [
        {
            "maintenance_state": "returned",
            "maintenance": SimpleNamespace(
                sent_date=date(2026, 11, 1),
                returned_date=date(2026, 11, 11),
                vendor=SimpleNamespace(name="FixTech"),
            ),
        },
        {
            "maintenance_state": "returned",
            "maintenance": SimpleNamespace(
                sent_date=date(2026, 11, 1),
                returned_date=date(2026, 11, 21),
                vendor=SimpleNamespace(name="FixTech"),
            ),
        },
    ]
    assert _vendor_averages(rows) == {"FixTech": 15}


async def test_summary_counts_every_status(dashboard: DashboardHarness) -> None:
    response = await dashboard.client.get("/api/dashboard/handovers/summary")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 6
    assert body["completed"] == 2
    assert body["by_status"] == {
        "draft": 1,
        "in_progress": 1,
        "ready": 0,
        "stalled": 1,
        "completed": 2,
        "closed_with_gaps": 0,
        "cancelled": 1,
    }


async def test_summary_per_stage_matrix(dashboard: DashboardHarness) -> None:
    body = (
        await dashboard.client.get("/api/dashboard/handovers/summary")
    ).json()

    assert set(body["stages"]) == {stage.value for stage in STAGE_ORDER}
    assert body["stages"]["device_status"] == {
        "passed": 4,
        "pending": 2,
        "failed": 0,
        "not_done": 0,
    }
    assert body["stages"]["recipient_check"] == {
        "passed": 2,
        "pending": 3,
        "failed": 0,
        "not_done": 1,
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
    # Active cases only. A not-done operation is an explicit decision, so it is
    # not counted as a missing step; pending operations still are.
    assert "recipient_check" not in counts
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
    assert len(row["stages"]) == 9
    assert [item["status"] for item in row["stages"]].count("not_done") == 1
    assert row["missing_steps"][0]["stage"] == "report_printed"
    not_done = next(
        item for item in row["missing_steps"] if item["status"] == "not_done"
    )
    assert not_done["stage"] == "recipient_check"


async def test_rows_filter_by_kind_and_search(
    dashboard: DashboardHarness,
) -> None:
    by_kind = await dashboard.client.get(
        "/api/dashboard/handovers", params={"kind": "maintenance"}
    )
    assert by_kind.status_code == 200, by_kind.text
    assert by_kind.json()["total"] == 0

    searched = await dashboard.client.get(
        "/api/dashboard/handovers", params={"q": "SN-STALLED"}
    )
    assert searched.status_code == 200, searched.text
    body = searched.json()
    assert body["total"] == 1
    assert body["items"][0]["handover"]["device_serial"] == "SN-STALLED"

    invalid = await dashboard.client.get(
        "/api/dashboard/handovers", params={"kind": "other"}
    )
    assert invalid.status_code == 422


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


async def test_dashboard_page_renders_seeded_data(
    dashboard: DashboardHarness,
) -> None:
    stalled_id = await _id_for(dashboard, "SN-STALLED")

    response = await dashboard.client.get("/")

    assert response.status_code == 200, response.text
    body = response.text
    assert "Handover" in body
    assert "Ready labs" in body
    assert "Complete" in body
    assert "Not complete" in body
    for name in ("ready", "complete", "not_complete", "waiting_user", "stalled", "warnings"):
        assert f'data-kpi="{name}"' in body
    assert 'data-handover-list' in body
    assert 'data-chart="per-day"' in body
    assert 'data-attention' in body
    assert 'data-activity' in body
    assert 'data-rail' in body and 'data-topbar' in body and 'data-bottomnav' in body


async def test_dashboard_tiles_expose_outcome_filters(
    dashboard: DashboardHarness,
) -> None:
    response = await dashboard.client.get("/")

    assert response.status_code == 200, response.text
    body = response.text
    assert "Ready labs" in body
    assert "Not complete" in body
    for name in ("ready", "complete", "not_complete", "waiting_user", "stalled", "warnings"):
        assert f'data-tile="{name}"' in body
    for period in ("today", "7d", "30d", "all"):
        assert f'data-period="{period}"' in body
    for company in ("all", "B.tech", "Nexta", "Mylo"):
        assert f'data-company="{company}"' in body


async def test_handovers_page_renders_and_filters(
    dashboard: DashboardHarness,
) -> None:
    response = await dashboard.client.get("/handovers")

    assert response.status_code == 200, response.text
    body = response.text
    assert "Handovers" in body
    assert "SN-COMP-1" in body
    assert "SN-STALLED" in body
    assert 'name="company"' in body
    assert 'name="outcome"' in body
    assert 'name="q"' in body

    searched = await dashboard.client.get("/handovers?q=STALLED")
    assert searched.status_code == 200
    assert "SN-STALLED" in searched.text
    assert "SN-COMP-1" not in searched.text

    completed = await dashboard.client.get("/handovers?status=completed")
    assert completed.status_code == 200
    assert "SN-COMP-1" in completed.text
    assert "SN-COMP-2" in completed.text
    assert "SN-DRAFT" not in completed.text

    empty = await dashboard.client.get("/handovers?q=does-not-exist")
    assert empty.status_code == 200
    assert "—" in empty.text
    assert "New handover" in empty.text  # the empty state is not a dead end

    invalid = await dashboard.client.get("/handovers?status=nonsense&kind=other")
    assert invalid.status_code == 200
    assert 'name="outcome"' in invalid.text


async def test_new_case_shortcut_opens_the_registration_drawer(
    dashboard: DashboardHarness,
) -> None:
    response = await dashboard.client.get("/handovers?new=1")

    assert response.status_code == 200, response.text
    body = response.text
    # The registration form is a drawer drawn by shell.js; the page only has
    # to carry the trigger and the marker that opens it.
    assert 'data-new-shortcut="handover"' in body
    assert 'data-open-new="handover"' in body
    assert "New handover" in body


async def test_case_page_renders_the_case(
    dashboard: DashboardHarness,
) -> None:
    handover_id = await _id_for(dashboard, "SN-STALLED")

    response = await dashboard.client.get(f"/handovers/{handover_id}")

    assert response.status_code == 200, response.text
    body = response.text
    assert "SN-STALLED" in body
    assert "Recipient" in body
    assert "Handover" in body
    assert "Not complete yet" in body
    assert f'href="/handovers/{handover_id}/history"' in body
    assert 'data-check-device' in body
    assert f'data-case-id="{handover_id}"' in body

    draft_id = await _id_for(dashboard, "SN-DRAFT")
    draft = await dashboard.client.get(f"/handovers/{draft_id}")
    assert draft.status_code == 200
    assert 'data-check-device' in draft.text


async def test_handover_case_uses_three_independent_panels(
    dashboard: DashboardHarness,
) -> None:
    handover_id = await _id_for(dashboard, "SN-DRAFT")

    response = await dashboard.client.get(f"/handovers/{handover_id}")

    assert response.status_code == 200, response.text
    body = response.text
    assert 'data-status-select' in body
    assert 'data-recipient-search' in body
    assert 'data-print-form' in body
    assert f'href="/handovers/{handover_id}/history"' in body


async def test_pages_carry_no_inline_scripts_or_styles(
    dashboard: DashboardHarness,
) -> None:
    """`script-src 'self'` and `style-src 'self'` block inline code outright."""
    for path in ("/", "/handovers", "/maintenance", "/sync"):
        response = await dashboard.client.get(path, follow_redirects=True)
        assert response.status_code == 200, path
        html = response.text
        assert "style=" not in html, f"{path} has an inline style attribute"
        assert "<script>" not in html, f"{path} has an inline script element"
        assert "javascript:" not in html, f"{path} has a javascript: URL"


async def test_handover_case_outcome_is_rendered_from_server_state(
    dashboard: DashboardHarness,
) -> None:
    complete_id = await _id_for(dashboard, "SN-COMP-1")
    complete = await dashboard.client.get(f"/handovers/{complete_id}")
    assert complete.status_code == 200
    assert 'data-case-outcome' in complete.text

    stalled_id = await _id_for(dashboard, "SN-STALLED")
    stalled = await dashboard.client.get(f"/handovers/{stalled_id}")
    assert "Not complete yet" in stalled.text


async def test_handover_outcome_dashboard_excludes_maintenance(
    dashboard: DashboardHarness,
) -> None:
    await _add(
        dashboard,
        serial="SN-READY-B1",
        engineer=ENGINEER_A,
        status="ready",
        created=datetime(2026, 10, 23, 9, 0),
        company="B.tech",
        recipient_mode="none",
    )
    await _add(
        dashboard,
        serial="SN-READY-B2",
        engineer=ENGINEER_B,
        status="ready",
        created=datetime(2026, 10, 24, 9, 0),
        company="B.tech",
        recipient_mode="none",
    )
    await _add(
        dashboard,
        serial="SN-READY-M1",
        engineer=ENGINEER_B,
        status="ready",
        created=datetime(2026, 10, 25, 9, 0),
        company="Mylo",
        recipient_mode="none",
    )
    await _add(
        dashboard,
        serial="SN-MAINT-1",
        engineer=ENGINEER_A,
        status="completed",
        created=datetime(2026, 10, 26, 9, 0),
        kind="maintenance",
        company="B.tech",
        stages=_stages(passed=ALL_PASSED),
    )

    response = await dashboard.client.get("/api/dashboard/handover?period=all")

    assert response.status_code == 200
    body = response.json()
    assert body["tiles"]["ready"] == 3
    companies = {row["company"]: row for row in body["by_company"]}
    assert companies["B.tech"]["ready"] == 2
    assert companies["Mylo"]["ready"] == 1
    assert sum(row["ready"] for row in body["by_company"]) == body["tiles"]["ready"]
    assert body["tiles"]["complete"] == 2
    assert body["tiles"]["not_complete"] == 3


async def test_case_history_page_renders_the_audit_trail(
    dashboard: DashboardHarness,
) -> None:
    handover_id = await _id_for(dashboard, "SN-STALLED")

    response = await dashboard.client.get(f"/handovers/{handover_id}/history")

    assert response.status_code == 200, response.text
    body = response.text
    assert "History" in body
    assert "SN-STALLED" in body
    assert f'href="/handovers/{handover_id}"' in body


async def test_legacy_case_urls_redirect_permanently(
    dashboard: DashboardHarness,
) -> None:
    handover_id = await _id_for(dashboard, "SN-STALLED")

    listing = await dashboard.client.get("/cases?status=stalled")
    assert listing.status_code == 308
    assert listing.headers["location"] == "/handovers?status=stalled"

    detail = await dashboard.client.get(f"/cases/{handover_id}")
    assert detail.status_code == 308
    assert detail.headers["location"] == f"/handovers/{handover_id}"

    history = await dashboard.client.get(f"/cases/{handover_id}/history")
    assert history.status_code == 308
    assert history.headers["location"] == f"/handovers/{handover_id}/history"

    dashboard_url = await dashboard.client.get("/dashboard")
    assert dashboard_url.status_code == 308
    assert dashboard_url.headers["location"] == "/"

    new_case = await dashboard.client.get("/new?ticket_ref=LAB-7")
    assert new_case.status_code == 308
    assert new_case.headers["location"] == "/handovers?ticket_ref=LAB-7&new=1"


async def test_device_check_url_moves_to_sync_and_keeps_the_case(
    dashboard: DashboardHarness,
) -> None:
    handover_id = await _id_for(dashboard, "SN-STALLED")

    legacy = await dashboard.client.get(f"/device-check?handover_id={handover_id}")
    assert legacy.status_code == 308
    assert (
        legacy.headers["location"]
        == f"/sync?handover_id={handover_id}"
    )

    sync_page = await dashboard.client.get(f"/sync?handover_id={handover_id}")
    assert sync_page.status_code == 200
    assert f'href="/handovers/{handover_id}"' in sync_page.text
    assert "Return to case" in sync_page.text


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
    dashboard_page = await dashboard.client.get("/")
    sync_page = await dashboard.client.get("/sync")

    assert listing.status_code == 307
    assert listing.headers["location"] == "/login"
    assert detail.status_code == 307
    assert detail.headers["location"] == "/login"
    assert dashboard_page.status_code == 307
    assert dashboard_page.headers["location"] == "/login"
    assert sync_page.status_code == 307
    assert sync_page.headers["location"] == "/login"


async def test_unknown_case_page_is_404(
    dashboard: DashboardHarness,
) -> None:
    response = await dashboard.client.get(f"/handovers/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_unknown_case_history_page_is_404(
    dashboard: DashboardHarness,
) -> None:
    response = await dashboard.client.get(f"/handovers/{uuid.uuid4()}/history")

    assert response.status_code == 404


def test_pages_and_static_assets_work_outside_the_repository_cwd(
    make_client, monkeypatch, tmp_path
) -> None:
    """Uvicorn may be launched from any directory without TemplateNotFound."""
    monkeypatch.chdir(tmp_path)
    client, _ = make_client(ENABLE_DIAG="true")

    page = client.get("/", headers={"Accept": "text/html"})
    error = client.get("/missing", headers={"Accept": "text/html"})
    diagnostic = client.get("/diag/clipboard", headers={"Accept": "text/html"})
    static = client.get("/static/css/app.css")

    assert page.status_code == 200 and "Dashboard" in page.text
    assert error.status_code == 404 and "Page not found" in error.text
    assert diagnostic.status_code == 200
    assert static.status_code == 200


async def test_maintenance_dashboard_groups_only_maintenance_cases(
    dashboard: DashboardHarness,
) -> None:
    async with dashboard.factory() as session:
        vendor_a = MaintenanceDestination(name="Vendor A", name_key="vendor a")
        vendor_b = MaintenanceDestination(name="Vendor B", name_key="vendor b")
        session.add_all([vendor_a, vendor_b])
        await session.flush()
        rows = [
            ("M-1", "Model A", "B.tech", "with_it", vendor_a, date(2026, 11, 20)),
            ("M-2", "Model B", "Nexta", "with_it", vendor_b, date(2026, 11, 21)),
            ("M-3", "Model A", "Mylo", "at_vendor", vendor_a, date(2026, 11, 10)),
            ("M-4", "Model B", "B.tech", "at_vendor", vendor_b, date(2026, 11, 15)),
        ]
        for serial, model, company, state, vendor, received in rows:
            handover = Handover(
                kind="maintenance",
                status="in_progress",
                maintenance_state=state,
                engineer_email=ENGINEER_A[1],
                engineer_name=ENGINEER_A[0],
                device_serial=serial,
                device_model=model,
                device_company=company,
                created_at=NOW,
                updated_at=NOW,
            )
            handover.maintenance = MaintenanceInfo(
                handover_id=handover.id,
                received_date=received,
                destination_id=vendor.id,
                destination=vendor,
                diagnosis_category="Screen",
            )
            session.add(handover)
        session.add(
            _handover(
                serial="H-1",
                engineer=ENGINEER_A,
                status="in_progress",
                created=NOW,
                company="B.tech",
            )
        )
        await session.commit()

    response = await dashboard.client.get("/api/dashboard/maintenance")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["needs"]["total"] == 2
    assert body["in_maintenance"]["total"] == 2
    assert body["needs"]["by_company"] == [
        {"name": "B.tech", "count": 1},
        {"name": "Nexta", "count": 1},
    ]
    assert body["in_maintenance"]["by_vendor"] == [
        {"name": "Vendor A", "count": 1},
        {"name": "Vendor B", "count": 1},
    ]
    assert sum(item["count"] for item in body["needs"]["by_model"]) == 2
    assert sum(item["count"] for item in body["in_maintenance"]["by_company"]) == 2
    assert len(body["devices"]) == 4
    assert all(item["serial"] != "H-1" for item in body["devices"])


# -- Round 2: full handover operations dashboard ----------------------------


async def _seed_round_two(harness: DashboardHarness) -> None:
    async with harness.factory() as session:
        ready_b = _handover(
            serial="SN-R2-READY-B",
            engineer=ENGINEER_A,
            status="ready",
            created=NOW - timedelta(hours=3),
            company="B.tech",
            recipient_mode="none",
        )
        ready_b.device_model = "Latitude 5440"
        ready_m = _handover(
            serial="SN-R2-READY-M",
            engineer=ENGINEER_B,
            status="ready",
            created=NOW - timedelta(hours=5),
            company="Mylo",
            recipient_mode="none",
        )
        ready_m.device_model = "Latitude 5440"
        waiting = _handover(
            serial="SN-R2-WAITING",
            engineer=ENGINEER_A,
            status="in_progress",
            created=NOW - timedelta(days=3),
            updated=NOW - timedelta(days=2),
            company="B.tech",
            recipient_mode="pending_user",
        )
        warning = _handover(
            serial="SN-R2-WARNING",
            engineer=ENGINEER_B,
            status="in_progress",
            created=NOW - timedelta(hours=8),
            company="B.tech",
            recipient_mode="snipeit",
            recipient_company="Mylo",
            stages=_stages(failed=(Stage.SOFTWARE_CHECK,)),
        )
        session.add_all([ready_b, ready_m, waiting, warning])
        await session.flush()
        session.add_all(
            [
                Event(
                    handover_id=warning.id,
                    actor=ENGINEER_B[1],
                    type="company_mismatch_warning",
                    detail={
                        "device_company": "B.tech",
                        "recipient_company": "Mylo",
                        "engineer": ENGINEER_B[1],
                    },
                ),
                Event(
                    handover_id=ready_b.id,
                    actor=ENGINEER_A[1],
                    type="handover_created",
                    detail={},
                ),
                Event(
                    handover_id=waiting.id,
                    actor=ENGINEER_A[1],
                    type="pending_user_found",
                    detail={"username": "ali.hassan"},
                ),
            ]
        )
        await session.commit()


async def test_handover_dashboard_has_every_block_and_sums(
    dashboard: DashboardHarness,
) -> None:
    await _seed_round_two(dashboard)

    response = await dashboard.client.get("/api/dashboard/handover?period=all")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "period",
        "company",
        "tiles",
        "by_company",
        "ready_by_model",
        "per_day",
        "missing_parts",
        "by_engineer",
        "attention",
        "activity",
    }
    tiles = body["tiles"]
    assert tiles["ready"] == 2
    assert tiles["complete"] == 2
    assert tiles["not_complete"] == 5
    assert tiles["waiting_user"] == 1
    assert tiles["warnings"] == 1
    assert tiles["stalled"] >= 1
    assert tiles["avg_hours_to_complete"] is not None
    assert tiles["median_hours_to_complete"] is not None
    assert 0 <= tiles["within_24h_percent"] <= 100

    def total(field: str) -> int:
        return sum(row[field] for row in body["by_company"])

    assert total("ready") == tiles["ready"]
    assert total("complete") == tiles["complete"]
    assert total("not_complete") == tiles["not_complete"]
    assert total("waiting_user") == tiles["waiting_user"]

    assert body["ready_by_model"][0]["total"] == 2
    assert body["per_day"]
    assert body["missing_parts"]
    assert body["by_engineer"]
    assert body["attention"]
    assert body["activity"]
    assert body["attention"][0]["reason"]
    assert body["activity"][0]["text"]


async def test_handover_dashboard_period_shapes(
    dashboard: DashboardHarness,
) -> None:
    expected = {"today": 1, "7d": 7, "30d": 30, "all": 30}
    for period, points in expected.items():
        response = await dashboard.client.get(
            f"/api/dashboard/handover?period={period}"
        )
        assert response.status_code == 200, response.text
        assert len(response.json()["per_day"]) == points


async def test_handover_dashboard_company_filter_applies_everywhere(
    dashboard: DashboardHarness,
) -> None:
    await _seed_round_two(dashboard)

    response = await dashboard.client.get(
        "/api/dashboard/handover?period=all&company=Mylo"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["company"] == "Mylo"
    assert body["tiles"]["ready"] == 1
    assert body["tiles"]["warnings"] == 0
    assert all(
        row["company"] == "Mylo" or not any(row[key] for key in ("ready", "complete", "not_complete", "waiting_user"))
        for row in body["by_company"]
    )


async def test_handover_dashboard_cases_panel_filters(
    dashboard: DashboardHarness,
) -> None:
    await _seed_round_two(dashboard)

    ready = await dashboard.client.get(
        "/api/dashboard/handover/cases?filter=ready&period=all"
    )
    assert ready.status_code == 200, ready.text
    assert {item["device_serial"] for item in ready.json()["items"]} >= {
        "SN-R2-READY-B",
        "SN-R2-READY-M",
    }

    warnings = await dashboard.client.get(
        "/api/dashboard/handover/cases?filter=warnings&period=all"
    )
    assert "SN-R2-WARNING" in {
        item["device_serial"] for item in warnings.json()["items"]
    }

    waiting = await dashboard.client.get(
        "/api/dashboard/handover/cases?filter=waiting_user&period=all"
    )
    assert "SN-R2-WAITING" in {
        item["device_serial"] for item in waiting.json()["items"]
    }

    missing = await dashboard.client.get(
        "/api/dashboard/handover/cases?filter=missing&stage=software_check&period=all"
    )
    assert "SN-R2-WARNING" in {
        item["device_serial"] for item in missing.json()["items"]
    }
