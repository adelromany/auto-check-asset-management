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
from app.db.models.handover import Handover, HandoverStage
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
) -> Handover:
    return Handover(
        status=status,
        kind=kind,
        device_company=company,
        recipient_mode=recipient_mode,
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
    assert "Not complete yet" in body
    assert 'data-outcome="ready"' in body
    assert 'data-outcome="complete"' in body
    assert 'data-outcome="not_complete"' in body
    assert 'data-handover-list' in body
    assert 'data-rail' in body and 'data-topbar' in body and 'data-bottomnav' in body


async def test_dashboard_tiles_expose_outcome_filters(
    dashboard: DashboardHarness,
) -> None:
    response = await dashboard.client.get("/")

    assert response.status_code == 200, response.text
    body = response.text
    assert "Ready labs" in body
    assert "Not complete yet" in body
    assert 'data-ready-count' in body
    assert 'data-complete-count' in body
    assert 'data-not-complete-count' in body


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

    response = await dashboard.client.get("/api/dashboard/handover")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"]["total"] == 3
    assert body["ready"]["by_company"] == [
        {"company": "B.tech", "count": 2},
        {"company": "Mylo", "count": 1},
    ]
    assert body["complete"]["total"] == 2
    assert body["not_complete"]["total"] == 3


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
