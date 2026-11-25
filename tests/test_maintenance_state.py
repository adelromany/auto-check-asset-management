"""Regression tests for single-state invariant and duplicate prevention (FIX 12)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.handover import Handover, HandoverStage
from app.domain.maintenance_rules import MaintenanceState, derive_maintenance_state
from app.repositories.maintenance import case_state_filter
from tests.test_handovers_api import ApiHarness, api  # noqa: F401

_STAGE_STATUSES = ("pending", "passed", "failed", "not_done")


@pytest.mark.parametrize("received", _STAGE_STATUSES)
@pytest.mark.parametrize("sent_out", _STAGE_STATUSES)
@pytest.mark.parametrize("returned", _STAGE_STATUSES)
def test_derive_maintenance_state_returns_single_valid_state_for_every_combination(
    received: str,
    sent_out: str,
    returned: str,
) -> None:
    state = derive_maintenance_state(
        {
            "received": received,
            "sent_out": sent_out,
            "returned": returned,
        }
    )
    assert isinstance(state, MaintenanceState)
    assert state in {
        MaintenanceState.WITH_IT,
        MaintenanceState.AT_VENDOR,
        MaintenanceState.RETURNED,
    }
    if returned == "passed":
        assert state == MaintenanceState.RETURNED
    elif sent_out == "passed":
        assert state == MaintenanceState.AT_VENDOR
    else:
        assert state == MaintenanceState.WITH_IT


async def test_batch_send_moves_case_out_of_with_it_and_into_at_vendor(
    api: ApiHarness,
) -> None:
    vendor = await api.client.post(
        "/api/maintenance/vendors", json={"name": "State Vendor"}
    )
    assert vendor.status_code in (200, 201), vendor.text
    created = await api.client.post(
        "/api/maintenance/cases", json={"serial": "SN-10"}
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]

    send_res = await api.client.post(
        "/api/maintenance/batches/send",
        json={
            "case_ids": [case_id],
            "vendor_id": vendor.json()["id"],
            "sent_date": date.today().isoformat(),
        },
    )
    assert send_res.status_code == 200, send_res.text
    assert send_res.json()[0]["ok"] is True

    with_it = await api.client.get(
        "/api/maintenance/cases", params={"state": "with_it"}
    )
    at_vendor = await api.client.get(
        "/api/maintenance/cases", params={"state": "at_vendor"}
    )
    returned = await api.client.get(
        "/api/maintenance/cases", params={"state": "returned"}
    )
    assert with_it.status_code == 200
    assert at_vendor.status_code == 200
    assert returned.status_code == 200

    assert case_id not in [item["case_id"] for item in with_it.json()]
    assert case_id in [item["case_id"] for item in at_vendor.json()]
    assert case_id not in [item["case_id"] for item in returned.json()]


async def test_batch_receive_places_case_only_in_returned(
    api: ApiHarness,
) -> None:
    vendor = await api.client.post(
        "/api/maintenance/vendors", json={"name": "Return Vendor"}
    )
    created = await api.client.post(
        "/api/maintenance/cases", json={"serial": "SN-10"}
    )
    case_id = created.json()["id"]

    await api.client.post(
        "/api/maintenance/batches/send",
        json={
            "case_ids": [case_id],
            "vendor_id": vendor.json()["id"],
            "sent_date": date.today().isoformat(),
        },
    )
    receive_res = await api.client.post(
        "/api/maintenance/batches/receive",
        json={
            "case_ids": [case_id],
            "returned_date": date.today().isoformat(),
        },
    )
    assert receive_res.status_code == 200, receive_res.text
    assert receive_res.json()[0]["ok"] is True

    with_it = await api.client.get(
        "/api/maintenance/cases", params={"state": "with_it"}
    )
    at_vendor = await api.client.get(
        "/api/maintenance/cases", params={"state": "at_vendor"}
    )
    returned = await api.client.get(
        "/api/maintenance/cases", params={"state": "returned"}
    )
    assert case_id not in [item["case_id"] for item in with_it.json()]
    assert case_id not in [item["case_id"] for item in at_vendor.json()]
    assert case_id in [item["case_id"] for item in returned.json()]


async def test_dashboard_counts_sent_device_only_in_in_maintenance(
    api: ApiHarness,
) -> None:
    vendor = await api.client.post(
        "/api/maintenance/vendors", json={"name": "Dash Vendor"}
    )
    created = await api.client.post(
        "/api/maintenance/cases", json={"serial": "SN-10"}
    )
    case_id = created.json()["id"]

    await api.client.post(
        "/api/maintenance/batches/send",
        json={
            "case_ids": [case_id],
            "vendor_id": vendor.json()["id"],
            "sent_date": date.today().isoformat(),
        },
    )

    dash = await api.client.get("/api/dashboard/maintenance")
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["needs"]["total"] == 0
    assert body["in_maintenance"]["total"] == 1

    needs_ids = {
        d["case_id"] for d in body["devices"] if d["state"] == "with_it"
    }
    in_maint_ids = {
        d["case_id"] for d in body["devices"] if d["state"] == "at_vendor"
    }
    assert needs_ids.isdisjoint(in_maint_ids)
    assert case_id not in needs_ids
    assert case_id in in_maint_ids


async def test_duplicate_active_maintenance_case_returns_409(
    api: ApiHarness,
) -> None:
    first = await api.client.post(
        "/api/maintenance/cases", json={"serial": "SN-10"}
    )
    assert first.status_code == 201, first.text

    second = await api.client.post(
        "/api/maintenance/cases", json={"serial": "sn-10"}
    )
    assert second.status_code == 409, second.text


async def test_sending_same_case_twice_fails_second_time(
    api: ApiHarness,
) -> None:
    vendor = await api.client.post(
        "/api/maintenance/vendors", json={"name": "Twice Vendor"}
    )
    created = await api.client.post(
        "/api/maintenance/cases", json={"serial": "SN-10"}
    )
    case_id = created.json()["id"]
    payload = {
        "case_ids": [case_id],
        "vendor_id": vendor.json()["id"],
        "sent_date": date.today().isoformat(),
    }

    first_send = await api.client.post(
        "/api/maintenance/batches/send", json=payload
    )
    assert first_send.status_code == 200, first_send.text
    assert first_send.json()[0]["ok"] is True

    second_send = await api.client.post(
        "/api/maintenance/batches/send", json=payload
    )
    assert second_send.status_code == 200, second_send.text
    result = second_send.json()[0]
    assert result["ok"] is False
    assert "Not with IT" in result["error"]


async def test_case_state_filter_partitions_30_mixed_cases_without_overlap() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    now = datetime.now(timezone.utc)
    patterns = [
        # (received, sent_out, returned) -> expected state
        ("passed", "pending", "pending"),
        ("passed", "failed", "pending"),
        ("passed", "not_done", "pending"),
        ("passed", "passed", "pending"),
        ("passed", "passed", "failed"),
        ("passed", "passed", "passed"),
        ("pending", "passed", "pending"),
        ("pending", "pending", "passed"),
        ("failed", "not_done", "not_done"),
        ("passed", "not_done", "passed"),
    ]
    seeded_ids: set[str] = set()
    async with session_factory() as session:
        for idx in range(30):
            rec, sent, ret = patterns[idx % len(patterns)]
            h = Handover(
                kind="maintenance",
                status="in_progress",
                maintenance_state="with_it",  # deliberately stale to prove stage derivation
                engineer_email="eng@example.com",
                engineer_name="Engineer",
                device_serial=f"MIX-{idx:03d}",
                created_at=now,
                updated_at=now,
            )
            session.add(h)
            await session.flush()
            seeded_ids.add(str(h.id))
            session.add_all(
                [
                    HandoverStage(handover_id=h.id, stage="received", status=rec),
                    HandoverStage(handover_id=h.id, stage="sent_out", status=sent),
                    HandoverStage(handover_id=h.id, stage="returned", status=ret),
                ]
            )
        await session.commit()

        async def ids_for(state: str) -> set[str]:
            res = await session.execute(
                select(Handover.id).where(
                    Handover.kind == "maintenance",
                    case_state_filter(state),
                )
            )
            return {str(row[0]) for row in res.all()}

        with_it_ids = await ids_for("with_it")
        at_vendor_ids = await ids_for("at_vendor")
        returned_ids = await ids_for("returned")

    assert with_it_ids.isdisjoint(at_vendor_ids)
    assert with_it_ids.isdisjoint(returned_ids)
    assert at_vendor_ids.isdisjoint(returned_ids)
    assert (with_it_ids | at_vendor_ids | returned_ids) == seeded_ids
    await engine.dispose()

