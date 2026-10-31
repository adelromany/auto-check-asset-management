"""Phase 5: Snipe-IT write operations against the stateful fake."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx
from fastapi import HTTPException
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.clients.snipeit as snipeit
import app.db.models  # noqa: F401  (registers every table on Base.metadata)
import app.dependencies
import app.main
from app.db.base import Base
from app.services.sessions import SessionStore
from tests.fakes.snipeit_fake import SnipeItFake

ENGINEER = {"name": "Engineer One", "email": "engineer@example.com"}
BOB = {"id": 2, "name": "Bob", "username": "bob"}
ALICE_ID = 1


@dataclass
class OpsHarness:
    app: FastAPI
    client: httpx.AsyncClient
    fake: SnipeItFake


@pytest_asyncio.fixture()
async def ops():
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
    http_client = httpx.AsyncClient(transport=fake.transport)
    live_client = snipeit.SnipeItClient(
        "http://snipeit.test",
        snipeit.ServiceAccountProvider(fake.token),
        http_client=http_client,
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
        yield live_client

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
        yield OpsHarness(app=application, client=client, fake=fake)

    await http_client.aclose()
    await engine.dispose()


async def _create(api: OpsHarness, serial: str = "SN-10") -> str:
    response = await api.client.post(
        "/api/handovers", json={"device_serial": serial}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _confirm(api: OpsHarness, handover_id: str, stage: str) -> dict:
    response = await api.client.post(
        f"/api/handovers/{handover_id}/stages/{stage}/confirm"
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _agent_report(
    api: OpsHarness,
    handover_id: str,
    serial: str,
    username: str = "alice",
) -> None:
    session_response = await api.client.get(
        f"/api/session/new?handover_id={handover_id}"
    )
    code = session_response.json()["code"]
    submit = await api.client.post(
        f"/api/session/{code}/submit",
        json={
            "serial": serial,
            "username": username,
            "user_domain": "TESTDOMAIN",
            "console_user": f"TESTDOMAIN\\{username}",
            "cpu": "Intel Core i7",
            "ram_gb": 16,
            "disks": [{"name": "NVMe", "size_gb": 512, "type": "SSD"}],
            "software_checks": [
                {"id": software_id, "name": software_id, "installed": True}
                for software_id in ("forticlient", "sccm", "intune", "office2021")
            ],
            "windows_activation": {"status": "Licensed", "status_code": 1},
        },
    )
    assert submit.status_code == 200, submit.text


async def _ready(
    api: OpsHarness,
    *,
    serial: str = "SN-10",
    reported: str = "alice",
    confirm_recipient: bool = True,
) -> str:
    handover_id = await _create(api, serial)
    await _confirm(api, handover_id, "device_prepared")
    await _confirm(api, handover_id, "user_signed_in")
    await _agent_report(api, handover_id, serial, reported)
    if confirm_recipient:
        response = await api.client.post(
            f"/api/handovers/{handover_id}/recipient/confirm",
            json={"snipeit_user_id": ALICE_ID},
        )
        assert response.status_code == 200, response.text
    return handover_id


def _stage(body: dict, key: str) -> dict:
    return next(item for item in body["stages"] if item["stage"] == key)


def _post_paths(api: OpsHarness) -> list[str]:
    return [path for method, path, _ in api.fake.calls if method == "POST"]


# -- recipient --------------------------------------------------------------


async def test_recipient_search_returns_candidates_and_reported_match(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(
        ops, reported="alice", confirm_recipient=False
    )

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/recipient/search?q=alice"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reported_username"] == "alice"
    assert body["warning"] is None
    assert [item["id"] for item in body["candidates"]] == [1]
    assert body["candidates"][0]["matches_reported"] is True


async def test_recipient_search_warns_when_the_agent_reported_the_engineer(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(
        ops, reported="engineer", confirm_recipient=False
    )

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/recipient/search?q=alice"
    )

    assert response.status_code == 200
    assert "may have been run elevated" in response.json()["warning"]


async def test_recipient_confirmation_requires_engineer_identity_acknowledgement(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops, reported="engineer", confirm_recipient=False)
    without_ack = await ops.client.post(
        f"/api/handovers/{handover_id}/recipient/confirm",
        json={"snipeit_user_id": ALICE_ID},
    )
    assert without_ack.status_code == 409
    assert "acknowledgement" in without_ack.json()["detail"]

    accepted = await ops.client.post(
        f"/api/handovers/{handover_id}/recipient/confirm",
        json={"snipeit_user_id": ALICE_ID, "acknowledge_same_as_engineer": True},
    )
    assert accepted.status_code == 200, accepted.text


async def test_software_override_api_validates_reason_and_state(ops: OpsHarness) -> None:
    handover_id = await _create(ops)
    await _confirm(ops, handover_id, "device_prepared")
    await _confirm(ops, handover_id, "user_signed_in")
    session_response = await ops.client.get(
        f"/api/session/new?handover_id={handover_id}"
    )
    code = session_response.json()["code"]
    payload = {
        "serial": "SN-10", "username": "alice", "user_domain": "TESTDOMAIN",
        "hostname": "WS-1", "cpu": "Intel Core i7", "ram_gb": 16,
        "disks": [{"name": "NVMe", "size_gb": 512, "type": "SSD"}],
        "software_checks": [
            {"id": name, "name": name, "installed": name != "office2021"}
            for name in ("forticlient", "sccm", "intune", "office2021")
        ],
        "windows_activation": {"status": "Licensed", "status_code": 1},
    }
    submitted = await ops.client.post(f"/api/session/{code}/submit", json=payload)
    assert submitted.status_code == 200

    short_reason = await ops.client.post(
        f"/api/handovers/{handover_id}/software-check/override",
        json={"reason": "123456789"},
    )
    assert short_reason.status_code == 422
    accepted = await ops.client.post(
        f"/api/handovers/{handover_id}/software-check/override",
        json={"reason": "Temporary approved exception"},
    )
    assert accepted.status_code == 200, accepted.text
    assert _stage(accepted.json(), "software_check")["status"] == "skipped"
    repeated = await ops.client.post(
        f"/api/handovers/{handover_id}/software-check/override",
        json={"reason": "Another approved exception"},
    )
    assert repeated.status_code == 409


async def test_software_override_api_authentication_and_csrf(
    ops: OpsHarness, monkeypatch
) -> None:
    handover_id = await _create(ops)
    no_session_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ops.app), base_url="http://test"
    )
    try:
        monkeypatch.setattr(app.config, "SSO_ENABLED", True)
        csrf = await no_session_client.post(
            f"/api/handovers/{handover_id}/software-check/override",
            json={"reason": "Valid reason for an override"},
        )
        assert csrf.status_code == 403
    finally:
        await no_session_client.aclose()

    monkeypatch.setattr(app.config, "SSO_ENABLED", False)
    ops.app.dependency_overrides[app.dependencies.current_user] = lambda: (
        _unauthorized_user()
    )
    try:
        unauthenticated = await ops.client.post(
            f"/api/handovers/{handover_id}/software-check/override",
            json={"reason": "Valid reason for an override"},
        )
        assert unauthenticated.status_code == 401
    finally:
        ops.app.dependency_overrides[app.dependencies.current_user] = lambda: ENGINEER


def _unauthorized_user():
    raise HTTPException(status_code=401, detail="Not authenticated")


async def test_confirm_recipient_passes_stage_four(ops: OpsHarness) -> None:
    handover_id = await _ready(ops, confirm_recipient=False)

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/recipient/confirm",
        json={"snipeit_user_id": ALICE_ID},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recipient_snipeit_id"] == ALICE_ID
    assert body["recipient_snipeit_username"] == "alice"
    assert body["recipient_confirmed_by"] == ENGINEER["email"]
    assert body["recipient_confirmed_at"] is not None
    assert _stage(body, "recipient_check")["status"] == "passed"
    assert body["events"][-1]["type"] == "recipient_confirmed"


async def test_confirm_recipient_is_idempotent_for_the_same_user(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops)
    before = (
        await ops.client.get(f"/api/handovers/{handover_id}")
    ).json()

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/recipient/confirm",
        json={"snipeit_user_id": ALICE_ID},
    )

    assert response.status_code == 200
    after = response.json()
    assert len(after["events"]) == len(before["events"])


async def test_confirm_recipient_not_in_snipeit_blocks_stage_four(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops, confirm_recipient=False)

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/recipient/confirm",
        json={"not_found": True},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    stage = _stage(body, "recipient_check")
    assert stage["status"] == "blocked"
    assert stage["reason"] == "Recipient not found in Snipe-IT"
    assert body["status"] == "stalled"
    assert body["recipient_snipeit_id"] is None
    assert body["events"][-1]["type"] == "recipient_not_found"


async def test_confirm_recipient_with_unknown_id_blocks_stage_four(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops, confirm_recipient=False)

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/recipient/confirm",
        json={"snipeit_user_id": 999},
    )

    assert response.status_code == 200
    assert _stage(response.json(), "recipient_check")["status"] == "blocked"


async def test_confirm_recipient_requires_the_agent_report(
    ops: OpsHarness,
) -> None:
    handover_id = await _create(ops)
    await _confirm(ops, handover_id, "device_prepared")

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/recipient/confirm",
        json={"snipeit_user_id": ALICE_ID},
    )

    assert response.status_code == 409
    assert "agent_report" in response.json()["detail"]


async def test_confirm_recipient_body_requires_exactly_one_choice(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops, confirm_recipient=False)

    neither = await ops.client.post(
        f"/api/handovers/{handover_id}/recipient/confirm", json={}
    )
    both = await ops.client.post(
        f"/api/handovers/{handover_id}/recipient/confirm",
        json={"snipeit_user_id": ALICE_ID, "not_found": True},
    )

    assert neither.status_code == 422
    assert both.status_code == 422


# -- preview ----------------------------------------------------------------


async def test_preview_lists_calls_and_makes_no_writes(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops)
    ops.fake.calls.clear()

    response = await ops.client.get(
        f"/api/handovers/{handover_id}/preview"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recipient_confirmed"] is True
    assert body["already_passed"] is False
    assert [call["action"] for call in body["calls"]] == [
        "checkout",
        "checkin",
    ]
    assert body["calls"][0]["asset_id"] == 10
    assert body["calls"][1]["asset_id"] == 11
    assert _post_paths(ops) == []


async def test_preview_warns_when_the_asset_is_missing(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops, serial="SN-MISSING")

    response = await ops.client.get(
        f"/api/handovers/{handover_id}/preview"
    )

    assert response.status_code == 200
    assert response.json()["calls"][0]["action"] == "checkin"
    assert any(
        "not found" in warning
        for warning in response.json()["warnings"]
    )


# -- checkout ---------------------------------------------------------------


async def test_checkout_happy_path_writes_once_and_verifies(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops)
    ops.fake.calls.clear()

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/checkout"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    stage = _stage(body, "checkout")
    assert stage["status"] == "passed"
    assert stage["detail"]["already_assigned"] is False
    assert body["snipeit_asset_id"] == 10
    assert ops.fake.assets[10]["assigned_to"]["id"] == ALICE_ID
    assert _post_paths(ops) == ["/api/v1/hardware/10/checkout"]
    note = ops.fake.checkout_notes[-1]
    assert ENGINEER["email"] in note
    assert handover_id in note
    assert body["events"][-1]["type"] == "checkout_attempt"


async def test_double_click_checkout_writes_only_once(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops)
    ops.fake.calls.clear()

    first = await ops.client.post(f"/api/handovers/{handover_id}/checkout")
    second = await ops.client.post(f"/api/handovers/{handover_id}/checkout")

    assert first.status_code == 200
    assert second.status_code == 200
    assert _stage(second.json(), "checkout")["status"] == "passed"
    assert _post_paths(ops) == ["/api/v1/hardware/10/checkout"]


async def test_checkout_refuses_when_the_asset_is_assigned_elsewhere(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops)
    ops.fake.assets[10]["assigned_to"] = dict(BOB)
    ops.fake.calls.clear()

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/checkout"
    )

    assert response.status_code == 200
    body = response.json()
    stage = _stage(body, "checkout")
    assert stage["status"] == "failed"
    assert "Bob" in stage["reason"]
    assert body["status"] == "stalled"
    assert _post_paths(ops) == []


async def test_checkout_fails_cleanly_when_the_serial_is_unknown(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops, serial="SN-MISSING")

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/checkout"
    )

    assert response.status_code == 200
    body = response.json()
    stage = _stage(body, "checkout")
    assert stage["status"] == "failed"
    assert stage["reason"] == "Asset serial not found in Snipe-IT"
    assert _post_paths(ops) == []


async def test_checkout_fails_when_verification_does_not_match(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops)
    ops.fake.checkout_assigns = False

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/checkout"
    )

    assert response.status_code == 200
    stage = _stage(response.json(), "checkout")
    assert stage["status"] == "failed"
    assert stage["reason"].startswith("Verification failed")
    assert _post_paths(ops) == ["/api/v1/hardware/10/checkout"]


async def test_checkout_network_failure_is_retryable(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops)
    ops.fake.fail_post_exception = httpx.ConnectError("down")
    ops.fake.calls.clear()

    failed = await ops.client.post(
        f"/api/handovers/{handover_id}/checkout"
    )

    assert failed.status_code == 200
    stage = _stage(failed.json(), "checkout")
    assert stage["status"] == "failed"
    assert "Could not reach Snipe-IT" in stage["reason"]
    assert _post_paths(ops) == ["/api/v1/hardware/10/checkout"]

    retried = await ops.client.post(
        f"/api/handovers/{handover_id}/checkout"
    )

    assert retried.status_code == 200
    assert _stage(retried.json(), "checkout")["status"] == "passed"


async def test_checkout_marks_passed_without_writing_when_already_assigned(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops)
    ops.fake.assets[10]["assigned_to"] = {
        "id": ALICE_ID,
        "name": "Alice",
        "username": "alice",
    }
    ops.fake.calls.clear()

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/checkout"
    )

    assert response.status_code == 200
    stage = _stage(response.json(), "checkout")
    assert stage["status"] == "passed"
    assert stage["detail"]["already_assigned"] is True
    assert _post_paths(ops) == []


# -- checkin ----------------------------------------------------------------


async def test_checkin_checks_in_an_old_device_and_verifies(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops)
    ops.fake.calls.clear()

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/checkin",
        json={"asset_ids": [11]},
    )

    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["status"] == "checked_in"
    assert ops.fake.assets[11]["assigned_to"] is None
    assert _post_paths(ops) == ["/api/v1/hardware/11/checkin"]

    detail = (
        await ops.client.get(f"/api/handovers/{handover_id}")
    ).json()
    assert detail["events"][-1]["type"] == "checkin_attempt"


async def test_checkin_is_idempotent_for_an_unassigned_asset(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops)
    ops.fake.assets[11]["assigned_to"] = None
    ops.fake.calls.clear()

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/checkin",
        json={"asset_ids": [11]},
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "already_unassigned"
    assert _post_paths(ops) == []


async def test_checkin_refuses_the_handover_device_and_foreign_assets(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops)
    ops.fake.assets[12] = {
        **ops.fake.assets[11],
        "id": 12,
        "asset_tag": "A-12",
        "serial": "SN-12",
        "assigned_to": dict(BOB),
    }
    ops.fake.calls.clear()

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/checkin",
        json={"asset_ids": [10, 12, 999]},
    )

    assert response.status_code == 200
    statuses = [item["status"] for item in response.json()["results"]]
    assert statuses == [
        "refused_handover_device",
        "not_recipient",
        "not_found",
    ]
    assert _post_paths(ops) == []


async def test_checkin_requires_a_confirmed_recipient(
    ops: OpsHarness,
) -> None:
    handover_id = await _ready(ops, confirm_recipient=False)

    response = await ops.client.post(
        f"/api/handovers/{handover_id}/checkin",
        json={"asset_ids": [11]},
    )

    assert response.status_code == 409
    assert "Recipient is not confirmed" in response.json()["detail"]


# -- shared -----------------------------------------------------------------


async def test_unknown_handover_returns_404(ops: OpsHarness) -> None:
    missing = uuid.uuid4()

    checkout = await ops.client.post(
        f"/api/handovers/{missing}/checkout"
    )
    search = await ops.client.post(
        f"/api/handovers/{missing}/recipient/search?q=alice"
    )
    preview = await ops.client.get(f"/api/handovers/{missing}/preview")

    assert checkout.status_code == 404
    assert search.status_code == 404
    assert preview.status_code == 404
