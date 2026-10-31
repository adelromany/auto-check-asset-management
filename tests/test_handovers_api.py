"""Phase 2 API tests: httpx.AsyncClient against the ASGI app."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401  (registers every table on Base.metadata)
import app.dependencies
import app.main
from app import config
from app.db.base import Base
from app.services.sessions import SessionStore

ENGINEER = {"name": "Engineer One", "email": "engineer@example.com"}


@dataclass
class ApiHarness:
    app: FastAPI
    client: httpx.AsyncClient
    store: SessionStore


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

    async def override_session():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[app.dependencies.get_session] = override_session
    application.dependency_overrides[app.dependencies.current_user] = lambda: ENGINEER
    application.dependency_overrides[app.dependencies.get_store] = lambda: store

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        csrf = await client.get("/api/me")
        client.headers["X-CSRF-Token"] = csrf.headers["X-CSRF-Token"]
        yield ApiHarness(app=application, client=client, store=store)

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


async def test_detail_includes_stages_missing_steps_and_timeline(
    api: ApiHarness,
) -> None:
    created = await _create(api)

    response = await api.client.get(f"/api/handovers/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert [stage["stage"] for stage in body["stages"]] == [
        "device_prepared",
        "user_signed_in",
        "agent_report",
        "software_check",
        "recipient_check",
        "checkout",
        "report_printed",
        "user_signed",
        "document_scanned",
        "document_pushed",
    ]
    assert all(stage["status"] == "pending" for stage in body["stages"])
    assert len(body["missing_steps"]) == 10
    assert all(item["hint"] for item in body["missing_steps"])
    assert [event["type"] for event in body["events"]] == ["handover_created"]


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


async def test_confirming_with_an_unmet_dependency_returns_409(
    api: ApiHarness,
) -> None:
    created = await _create(api)

    response = await api.client.post(
        f"/api/handovers/{created['id']}/stages/user_signed_in/confirm"
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "device_prepared" in detail
    assert "pending" in detail


async def test_confirming_a_manual_stage_updates_status_and_timeline(
    api: ApiHarness,
) -> None:
    created = await _create(api)

    response = await api.client.post(
        f"/api/handovers/{created['id']}/stages/device_prepared/confirm"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    stage = next(
        item for item in body["stages"] if item["stage"] == "device_prepared"
    )
    assert stage["status"] == "passed"
    assert stage["actor"] == ENGINEER["email"]
    assert [event["type"] for event in body["events"]] == [
        "handover_created",
        "stage_confirmed",
    ]


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
    assert "active handover already exists" in response.json()["detail"]


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
    api: ApiHarness,
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
    assert body["events"][-1]["type"] == "agent_report_received"
    assert body["events"][-1]["detail"]["matched"] is True


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
    assert body["status"] == "stalled"
    assert body["events"][-1]["detail"]["matched"] is False


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
