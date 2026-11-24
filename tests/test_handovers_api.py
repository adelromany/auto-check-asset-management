"""Phase 2 API tests: httpx.AsyncClient against the ASGI app."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401  (registers every table on Base.metadata)
import app.dependencies
import app.main
import app.clients.snipeit as snipeit
from app import config
from app.db.base import Base
from app.services.sessions import SessionStore
from tests.fakes.snipeit_fake import SnipeItFake

ENGINEER = {"name": "Engineer One", "email": "engineer@example.com"}
REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ApiHarness:
    app: FastAPI
    client: httpx.AsyncClient
    store: SessionStore
    fake: SnipeItFake


@pytest_asyncio.fixture()
async def api():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    application = app.main.create_app()
    store = SessionStore(ttl_seconds=600)
    fake = SnipeItFake()
    snipeit_http = httpx.AsyncClient(transport=fake.transport)
    snipeit_client = snipeit.SnipeItClient(
        "http://snipeit.test",
        snipeit.ServiceAccountProvider(fake.token),
        http_client=snipeit_http,
        engineer_email=ENGINEER["email"],
        retry_backoff=0.0,
    )

    async def override_session():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def override_snipeit_client():
        yield snipeit_client

    application.dependency_overrides[app.dependencies.get_session] = override_session
    application.dependency_overrides[app.dependencies.current_user] = lambda: ENGINEER
    application.dependency_overrides[app.dependencies.get_store] = lambda: store
    application.dependency_overrides[
        app.dependencies.get_snipeit_client
    ] = override_snipeit_client

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        csrf = await client.get("/api/me")
        client.headers["X-CSRF-Token"] = csrf.headers["X-CSRF-Token"]
        yield ApiHarness(
            app=application, client=client, store=store, fake=fake
        )

    await snipeit_http.aclose()
    await engine.dispose()


async def _create(api: ApiHarness, serial: str = "SN-1", **extra) -> dict:
    body = {"device_serial": serial, **extra}
    response = await api.client.post("/api/handovers", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_returns_a_draft_summary(api: ApiHarness) -> None:
    body = await _create(api, serial="SN-API-1", ticket_ref="LAB-42")

    assert body["device_serial"] == "SN-API-1"
    assert body["ticket_ref"] == "LAB-42"
    assert body["status"] == "draft"
    assert body["engineer_email"] == ENGINEER["email"]
    assert body["engineer_name"] == ENGINEER["name"]
    assert body["closed_at"] is None
    assert "stages" not in body


async def test_create_stores_the_device_facts_read_from_snipeit(
    api: ApiHarness,
) -> None:
    body = await _create(api, serial="SN-1")

    assert body["device_company"] == "B.tech"
    assert body["device_model"] == "ThinkPad T14"
    assert body["device_category"] == "Laptops"
    assert body["snipeit_status_name"] == "Ready"
    assert body["snipeit_asset_id"] == 10


async def test_create_rejects_a_serial_that_snipeit_does_not_know(
    api: ApiHarness,
) -> None:
    api.fake.fallback_asset_on_search = False

    response = await api.client.post(
        "/api/handovers", json={"device_serial": "SN-NOT-IN-SNIPEIT"}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Serial not found in Snipe-IT"
    listed = await api.client.get("/api/handovers")
    assert listed.json()["total"] == 0


async def test_create_reports_an_unreachable_snipeit(api: ApiHarness) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("snipeit is down", request=request)

    failing_http = httpx.AsyncClient(
        transport=httpx.MockTransport(boom)
    )
    failing_client = snipeit.SnipeItClient(
        "http://snipeit.test",
        snipeit.ServiceAccountProvider("token"),
        http_client=failing_http,
        retry_backoff=0.0,
    )

    async def override_snipeit_client():
        yield failing_client

    api.app.dependency_overrides[
        app.dependencies.get_snipeit_client
    ] = override_snipeit_client

    response = await api.client.post(
        "/api/handovers", json={"device_serial": "SN-OFFLINE"}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Snipe-IT is unreachable."
    listed = await api.client.get("/api/handovers")
    assert listed.json()["total"] == 0
    await failing_http.aclose()


async def test_detail_includes_stages_missing_steps_and_timeline(
    api: ApiHarness,
) -> None:
    created = await _create(api)

    response = await api.client.get(f"/api/handovers/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert [stage["stage"] for stage in body["stages"]] == [
        "device_status",
        "agent_report",
        "software_check",
        "report_printed",
        "recipient_check",
        "recipient_items",
        "checkout",
        "document_scanned",
        "document_pushed",
    ]
    assert all(stage["status"] == "pending" for stage in body["stages"])
    assert len(body["missing_steps"]) == 9
    assert all(item["hint"] for item in body["missing_steps"])
    assert [event["type"] for event in body["events"]] == ["handover_created"]


async def test_case_page_links_device_check_and_explains_manual_confirmations(
    api: ApiHarness, monkeypatch,
) -> None:
    created = await _create(api, serial="SN-LINKED-DEVICE-CHECK")
    handover_id = created["id"]
    monkeypatch.setattr(config, "SSO_ENABLED", False)

    case_page = await api.client.get(f"/handovers/{handover_id}")
    assert case_page.status_code == 200
    # The device-check entry point is the Sync button; the old /device-check
    # URL still moves to /sync and keeps the case.
    assert "data-sync-open" in case_page.text
    assert 'data-op-tile="report_printed"' in case_page.text
    assert 'data-op-tile="agent_report"' in case_page.text

    device_check = await api.client.get(
        f"/device-check?handover_id={handover_id}", follow_redirects=True
    )
    assert device_check.status_code == 200
    assert "Return to case" in device_check.text
    assert f'href="/handovers/{handover_id}"' in device_check.text

    # The drawer copy lives in case.js now (drawers are built client-side).
    case_js = (REPO_ROOT / "static" / "js" / "case.js").read_text(encoding="utf-8")
    assert "Manual confirmation" in case_js
    assert "does not collect evidence" in case_js


async def test_maintenance_page_lists_vendors_used_by_cases(
    api: ApiHarness, monkeypatch,
) -> None:
    """The vendor panel is built from the cases, not from the seed list."""
    created = await _create(api, serial="SN-VENDOR-PANEL", kind="maintenance")
    handover_id = created["id"]
    monkeypatch.setattr(config, "SSO_ENABLED", False)

    response = await api.client.post(
        f"/api/handovers/{handover_id}/maintenance",
        json={
            "vendor": "FixTech",
            "sent_date": "2026-11-02",
            "reference": "RMA-4471",
        },
    )
    assert response.status_code == 200, response.text
    confirmed = await api.client.post(
        f"/api/handovers/{handover_id}/operations/sent_out/confirm"
    )
    assert confirmed.status_code == 200, confirmed.text

    page = await api.client.get("/maintenance")
    assert page.status_code == 200
    assert "No vendor used yet." not in page.text
    assert "FixTech" in page.text
    assert "1 here" in page.text
    # The at-vendors table carries the same case.
    assert "SN-VENDOR-PANEL" in page.text
    assert "RMA-4471" in page.text


async def test_dashboard_attention_reason_counts_days_at_vendor(
    api: ApiHarness, monkeypatch,
) -> None:
    """An overdue repair shows how long the device has actually been away."""
    from datetime import date, timedelta

    sent = date.today() - timedelta(days=30)
    expected = date.today() - timedelta(days=16)
    created = await _create(api, serial="SN-OVERDUE-VENDOR", kind="maintenance")
    handover_id = created["id"]
    monkeypatch.setattr(config, "SSO_ENABLED", False)

    response = await api.client.post(
        f"/api/handovers/{handover_id}/maintenance",
        json={
            "vendor": "FixTech",
            "sent_date": sent.isoformat(),
            "expected_return_date": expected.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    confirmed = await api.client.post(
        f"/api/handovers/{handover_id}/operations/sent_out/confirm"
    )
    assert confirmed.status_code == 200, confirmed.text

    page = await api.client.get("/")
    assert page.status_code == 200
    # Never a "?" â€” the days run from the send date to today.
    assert "At vendor ? days" not in page.text
    assert "At vendor 30 days, overdue" in page.text


async def test_unauthorized_access_returns_401(
    api: ApiHarness, monkeypatch
) -> None:
    api.app.dependency_overrides.pop(app.dependencies.current_user, None)
    monkeypatch.setattr(config, "SSO_ENABLED", True)

    response = await api.client.get("/api/handovers")

    assert response.status_code == 401


async def test_invalid_stage_name_returns_422(api: ApiHarness) -> None:
    created = await _create(api)

    response = await api.client.post(
        f"/api/handovers/{created['id']}/stages/not_a_stage/confirm"
    )

    assert response.status_code == 422
    assert "Unknown stage" in response.json()["detail"]


async def _submit_agent_report(api: ApiHarness, serial: str, handover_id: str) -> None:
    session_response = await api.client.get(
        f"/api/session/new?handover_id={handover_id}"
    )
    code = session_response.json()["code"]
    submit = await api.client.post(
        f"/api/session/{code}/submit",
        json={
            "serial": serial,
            "cpu": "Intel Core i7",
            "ram_gb": 16,
            "disks": [{"name": "NVMe", "size_gb": 512, "type": "SSD"}],
        },
    )
    assert submit.status_code == 200


async def test_operations_are_independent_and_only_record_advice(
    api: ApiHarness,
) -> None:
    created = await _create(api, serial="SN-ADVICE")
    await _submit_agent_report(api, "SN-ADVICE", created["id"])

    response = await api.client.post(
        f"/api/handovers/{created['id']}/stages/report_printed/confirm"
    )

    assert response.status_code == 200
    body = response.json()
    stage = next(
        item for item in body["stages"] if item["stage"] == "report_printed"
    )
    assert stage["status"] == "passed"
    assert stage["detail"]["performed_before"] == ["software_check"]
    assert stage["detail"]["advice"] == [
        "Usually done after Software"
    ]


async def test_confirming_a_manual_stage_updates_status_and_timeline(
    api: ApiHarness,
) -> None:
    created = await _create(api, serial="SN-MANUAL")
    await _submit_agent_report(api, "SN-MANUAL", created["id"])

    response = await api.client.post(
        f"/api/handovers/{created['id']}/stages/report_printed/confirm"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    stage = next(
        item for item in body["stages"] if item["stage"] == "report_printed"
    )
    assert stage["status"] == "passed"
    assert stage["actor"] == ENGINEER["email"]
    assert [event["type"] for event in body["events"]] == [
        "handover_created",
        "operation_recorded",
        "operation_recorded",
        "operation_recorded",
    ]
    assert body["events"][-1]["detail"]["operation"] == "report_printed"
    assert body["events"][-1]["detail"]["outcome"] == "passed"


async def test_report_printed_can_be_confirmed_after_agent_report(
    api: ApiHarness,
) -> None:
    created = await _create(api, serial="SN-PRINT-REPORT")
    session_response = await api.client.get(
        f"/api/session/new?handover_id={created['id']}"
    )
    code = session_response.json()["code"]
    submit = await api.client.post(
        f"/api/session/{code}/submit",
        json={
            "serial": "SN-PRINT-REPORT",
            "cpu": "Intel Core i7",
            "ram_gb": 16,
            "disks": [{"name": "NVMe", "size_gb": 512, "type": "SSD"}],
        },
    )
    assert submit.status_code == 200

    printed = await api.client.post(
        f"/api/handovers/{created['id']}/stages/report_printed/confirm"
    )
    assert printed.status_code == 200
    printed_stage = next(
        item for item in printed.json()["stages"]
        if item["stage"] == "report_printed"
    )
    assert printed_stage["status"] == "passed"


async def test_confirming_a_non_manual_stage_returns_409(api: ApiHarness) -> None:
    created = await _create(api)

    response = await api.client.post(
        f"/api/handovers/{created['id']}/stages/checkout/confirm"
    )

    assert response.status_code == 409
    assert "cannot be confirmed manually" in response.json()["detail"]


async def test_duplicate_active_serial_returns_409(api: ApiHarness) -> None:
    await _create(api, serial="SN-DUP-API")

    response = await api.client.post(
        "/api/handovers", json={"device_serial": "SN-DUP-API"}
    )

    assert response.status_code == 409
    assert "already has an active handover case" in response.json()["detail"]


async def test_cancel_is_idempotent_and_blocks_further_work(
    api: ApiHarness,
) -> None:
    created = await _create(api)

    first = await api.client.post(f"/api/handovers/{created['id']}/cancel")
    second = await api.client.post(f"/api/handovers/{created['id']}/cancel")

    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    assert first.json()["closed_at"] is not None
    assert second.status_code == 200
    assert second.json()["status"] == "cancelled"

    confirm = await api.client.post(
        f"/api/handovers/{created['id']}/stages/device_prepared/confirm"
    )
    assert confirm.status_code == 409


async def test_not_done_requires_a_reason_and_stays_a_visible_gap(
    api: ApiHarness,
) -> None:
    created = await _create(api, serial="SN-NOT-DONE")

    too_short = await api.client.post(
        f"/api/handovers/{created['id']}/operations/recipient_check/not-done",
        json={"reason": "x"},
    )
    assert too_short.status_code == 422

    response = await api.client.post(
        f"/api/handovers/{created['id']}/operations/recipient_check/not-done",
        json={"reason": "Device not available"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    row = next(
        item for item in body["stages"] if item["stage"] == "recipient_check"
    )
    assert row["status"] == "not_done"
    assert row["reason"] == "Device not available"
    gap = next(
        item for item in body["missing_steps"]
        if item["stage"] == "recipient_check"
    )
    assert gap["status"] == "not_done"
    assert gap["hint"].startswith("Not done:")
    assert body["status"] == "in_progress"


async def test_close_with_gaps_requires_confirmation_and_reopen_clears_it(
    api: ApiHarness,
) -> None:
    created = await _create(api, serial="SN-CLOSE-GAPS")
    await api.client.post(
        f"/api/handovers/{created['id']}/operations/device_status/not-done",
        json={"reason": "Device not available"},
    )

    wrong = await api.client.post(
        f"/api/handovers/{created['id']}/close", json={"confirmation": "ok"}
    )
    assert wrong.status_code == 422

    closed = await api.client.post(
        f"/api/handovers/{created['id']}/close", json={"confirmation": "CLOSE"}
    )
    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["status"] == "closed_with_gaps"
    assert body["closed_at"] is not None
    assert [gap["operation"] for gap in body["closed_gaps"]][0] == (
        "device_status"
    )

    blocked = await api.client.post(
        f"/api/handovers/{created['id']}/stages/report_printed/confirm"
    )
    assert blocked.status_code == 409

    reopened = await api.client.post(
        f"/api/handovers/{created['id']}/reopen"
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "in_progress"
    assert reopened.json()["closed_gaps"] is None

    again = await api.client.post(f"/api/handovers/{created['id']}/reopen")
    assert again.status_code == 409


async def test_list_paginates_filters_and_caps_page_size(api: ApiHarness) -> None:
    first = await _create(api, serial="SN-LIST-A")
    second = await _create(api, serial="SN-LIST-B")
    await api.client.post(f"/api/handovers/{second['id']}/cancel")

    page_one = await api.client.get("/api/handovers?page=1&page_size=1")
    page_two = await api.client.get("/api/handovers?page=2&page_size=1")
    cancelled = await api.client.get("/api/handovers?status=cancelled")
    too_big = await api.client.get("/api/handovers?page_size=101")
    bad_status = await api.client.get("/api/handovers?status=nope")

    assert page_one.status_code == 200
    assert page_one.json()["total"] == 2
    assert len(page_one.json()["items"]) == 1
    assert len(page_two.json()["items"]) == 1
    assert {
        page_one.json()["items"][0]["id"],
        page_two.json()["items"][0]["id"],
    } == {first["id"], second["id"]}
    assert cancelled.json()["total"] == 1
    assert cancelled.json()["items"][0]["id"] == second["id"]
    assert too_big.status_code == 422
    assert bad_status.status_code == 422


async def test_unknown_handover_returns_404(api: ApiHarness) -> None:
    response = await api.client.get(f"/api/handovers/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_agent_flow_with_matching_serial_passes_stage_three(
    api: ApiHarness, monkeypatch,
) -> None:
    created = await _create(api, serial="SN-AGENT-OK")

    session_response = await api.client.get(
        f"/api/session/new?handover_id={created['id']}"
    )
    assert session_response.status_code == 200
    code = session_response.json()["code"]

    submit = await api.client.post(
        f"/api/session/{code}/submit",
        json={
            "serial": "SN-AGENT-OK",
            "username": "alice",
            "user_domain": "TESTDOMAIN",
            "cpu": "Intel Core i7",
            "ram_gb": 16,
            "disks": [{"name": "NVMe", "size_gb": 512, "type": "SSD"}],
            "software_checks": [
                {"id": software_id, "name": software_id, "installed": True}
                for software_id in ("forticlient", "sccm", "intune", "office2021")
            ],
            "windows_activation": {
                "status": "Licensed",
                "status_code": 1,
                "product_name": "Windows 11 Pro",
                "partial_key": "ABCDE",
            },
        },
    )
    assert submit.status_code == 200
    assert submit.json() == {"status": "ok"}

    detail = await api.client.get(f"/api/handovers/{created['id']}")
    body = detail.json()
    stage = next(item for item in body["stages"] if item["stage"] == "agent_report")
    assert stage["status"] == "passed"
    assert body["recipient_reported_username"] == "alice"
    assert body["status"] == "in_progress"
    recorded = [
        event for event in body["events"]
        if event["type"] == "operation_recorded"
    ]
    assert [event["detail"]["operation"] for event in recorded] == [
        "agent_report",
        "software_check",
    ]
    assert all(event["detail"]["outcome"] == "passed" for event in recorded)

    monkeypatch.setattr(config, "SSO_ENABLED", False)
    case_page = await api.client.get(f"/handovers/{created['id']}")
    assert "Agent report" in case_page.text
    assert "Intel Core i7" in case_page.text  # the CPU fact from the report
    assert "forticlient" in case_page.text  # software check listed by name
    assert "ABCDE" not in case_page.text  # the partial key is never shown


async def test_agent_flow_with_mismatched_serial_fails_stage_three(
    api: ApiHarness,
) -> None:
    created = await _create(api, serial="SN-AGENT-EXPECTED")

    session_response = await api.client.get(
        f"/api/session/new?handover_id={created['id']}"
    )
    code = session_response.json()["code"]
    submit = await api.client.post(
        f"/api/session/{code}/submit",
        json={"serial": "SN-OTHER", "username": "bob"},
    )
    assert submit.status_code == 200

    body = (await api.client.get(f"/api/handovers/{created['id']}")).json()
    stage = next(item for item in body["stages"] if item["stage"] == "agent_report")
    assert stage["status"] == "failed"
    assert "does not match" in stage["reason"]
    # A failed operation no longer stalls the case; the case stays open.
    assert body["status"] == "in_progress"
    software = next(
        item for item in body["stages"] if item["stage"] == "software_check"
    )
    assert software["detail"]["report_serial_differs"] is True
    recorded = {
        event["detail"]["operation"]: event["detail"]["outcome"]
        for event in body["events"]
        if event["type"] == "operation_recorded"
    }
    assert recorded["agent_report"] == "failed"
    # Software is evaluated anyway; an empty report fails its own check.
    assert recorded["software_check"] == "failed"


async def test_agent_flow_without_a_handover_is_unchanged(api: ApiHarness) -> None:
    session_response = await api.client.get("/api/session/new")
    assert session_response.status_code == 200
    assert set(session_response.json()) == {"code", "ttl_seconds"}
    code = session_response.json()["code"]

    submit = await api.client.post(
        f"/api/session/{code}/submit", json={"serial": "SN-NO-HANDOVER"}
    )
    assert submit.status_code == 200
    assert submit.json() == {"status": "ok"}

    # Idempotent second submit keeps the pre-Phase-2 response.
    again = await api.client.post(
        f"/api/session/{code}/submit", json={"serial": "SN-NO-HANDOVER"}
    )
    assert again.json() == {"status": "already_submitted"}


async def test_agent_flow_with_an_unknown_handover_still_accepts_the_report(
    api: ApiHarness,
) -> None:
    session_response = await api.client.get(
        f"/api/session/new?handover_id={uuid.uuid4()}"
    )
    code = session_response.json()["code"]

    submit = await api.client.post(
        f"/api/session/{code}/submit", json={"serial": "SN-UNKNOWN"}
    )

    assert submit.status_code == 200
    assert submit.json() == {"status": "ok"}


async def test_agent_session_rejects_a_non_uuid_handover_id(
    api: ApiHarness,
) -> None:
    response = await api.client.get("/api/session/new?handover_id=not-a-uuid")
    assert response.status_code == 422

