"""Integration tests for Maintenance cases, states, operations and API (Part D)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app import config
from app.domain.maintenance_rules import MaintenanceState
from tests.test_handovers_api import ApiHarness, _create, api


async def test_create_maintenance_case(api: ApiHarness) -> None:
    response = await api.client.post(
        "/api/handovers",
        json={
            "device_serial": "SN-MAINT-001",
            "ticket_ref": "FIX-101",
            "kind": "maintenance",
        },
    )
    assert response.status_code in (200, 201), response.text
    data = response.json()
    assert data["kind"] == "maintenance"
    assert data["device_serial"] == "SN-MAINT-001"
    assert data["maintenance_state"] == MaintenanceState.NEEDS_MAINTENANCE.value

    # Verify detail
    detail = await api.client.get(f"/api/handovers/{data['id']}")
    assert detail.status_code == 200
    body = detail.json()
    stages = [s["stage"] for s in body["stages"]]
    assert stages == ["received", "diagnosis", "snipeit_status", "sent_out", "returned"]
    assert all(s["status"] == "pending" for s in body["stages"])


async def test_update_maintenance_info_and_vendors(api: ApiHarness) -> None:
    created = await api.client.post(
        "/api/handovers",
        json={"device_serial": "SN-MAINT-INFO", "kind": "maintenance"},
    )
    case_id = created.json()["id"]

    # Update maintenance fields
    update_res = await api.client.post(
        f"/api/handovers/{case_id}/maintenance",
        json={
            "reported_issue": "Broken keyboard",
            "vendor": "FixTech",
            "condition_notes": "Scratches on chassis",
            "accessories": "Power adapter included",
            "diagnosis_category": "Keyboard",
            "reference": "RMA-1234",
        },
    )
    assert update_res.status_code == 200, update_res.text
    body = update_res.json()
    assert body["maintenance"] is not None
    assert body["maintenance"]["reported_issue"] == "Broken keyboard"
    assert body["maintenance"]["vendor"] == "FixTech"
    assert body["maintenance"]["reference"] == "RMA-1234"
    assert body["maintenance"]["diagnosis_category"] == "Keyboard"

    # Vendors list endpoint
    vendors_res = await api.client.get("/api/handovers/maintenance/vendors")
    assert vendors_res.status_code == 200
    vendors = vendors_res.json()
    assert any(v["name"] == "FixTech" for v in vendors)

    # Categories list endpoint
    cats_res = await api.client.get("/api/handovers/maintenance/categories")
    assert cats_res.status_code == 200
    categories = cats_res.json()
    assert any(c["name"] == "Keyboard" for c in categories)


async def test_transit_operations_derive_maintenance_states(api: ApiHarness) -> None:
    created = await api.client.post(
        "/api/handovers",
        json={"device_serial": "SN-MAINT-TRANSIT", "kind": "maintenance"},
    )
    case_id = created.json()["id"]

    # 1. Initially Needs maintenance
    detail = await api.client.get(f"/api/handovers/{case_id}")
    assert detail.json()["maintenance_state"] == "needs_maintenance"

    # Confirm received
    rx_res = await api.client.post(
        f"/api/handovers/{case_id}/operations/received/confirm"
    )
    assert rx_res.status_code == 200
    assert rx_res.json()["maintenance_state"] == "needs_maintenance"

    # 2. Sent out -> In maintenance
    send_date = (date.today() - timedelta(days=5)).isoformat()
    sent_res = await api.client.post(
        f"/api/handovers/{case_id}/operations/sent_out/confirm"
    )
    assert sent_res.status_code == 200
    assert sent_res.json()["maintenance_state"] == "in_maintenance"

    # 3. Returned -> Returned
    ret_res = await api.client.post(
        f"/api/handovers/{case_id}/operations/returned/confirm"
    )
    assert ret_res.status_code == 200
    assert ret_res.json()["maintenance_state"] == "returned"
    assert ret_res.json()["maintenance"]["returned_date"] is not None


async def test_maintenance_turnaround_and_overdue(api: ApiHarness) -> None:
    created = await api.client.post(
        "/api/handovers",
        json={"device_serial": "SN-MAINT-TURNAROUND", "kind": "maintenance"},
    )
    case_id = created.json()["id"]

    past_sent = date.today() - timedelta(days=20)
    past_due = date.today() - timedelta(days=5)

    # Update with overdue expected return date
    await api.client.post(
        f"/api/handovers/{case_id}/maintenance",
        json={
            "sent_date": past_sent.isoformat(),
            "expected_return_date": past_due.isoformat(),
        },
    )

    # Confirm sent_out
    sent_res = await api.client.post(
        f"/api/handovers/{case_id}/operations/sent_out/confirm"
    )
    m = sent_res.json()["maintenance"]
    assert m["is_overdue"] is True
    assert m["turnaround_days"] is None

    # Now returned today
    today = date.today()
    await api.client.post(
        f"/api/handovers/{case_id}/maintenance",
        json={"returned_date": today.isoformat()},
    )
    ret_res = await api.client.post(
        f"/api/handovers/{case_id}/operations/returned/confirm"
    )
    m2 = ret_res.json()["maintenance"]
    assert m2["is_overdue"] is False
    assert m2["turnaround_days"] == 20
