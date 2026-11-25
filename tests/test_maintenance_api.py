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
    assert data["maintenance_state"] == MaintenanceState.WITH_IT.value

    # Verify detail
    detail = await api.client.get(f"/api/handovers/{data['id']}")
    assert detail.status_code == 200
    body = detail.json()
    stages = [s["stage"] for s in body["stages"]]
    assert stages == [
        "received",
        "diagnosis",
        "snipeit_status",
        "taken_back",
        "sent_out",
        "returned",
        "ready_status",
    ]
    assert all(s["status"] == "pending" for s in body["stages"])


async def test_phase06_create_and_lookup_store_the_device_snapshot(
    api: ApiHarness,
) -> None:
    lookup = await api.client.get(
        "/api/maintenance/device-lookup", params={"serial": "SN-11"}
    )
    assert lookup.status_code == 200, lookup.text
    assert lookup.json()["model"] == "ThinkPad T14"
    assert lookup.json()["assigned_to"] == "Alice"

    reasons = await api.client.get("/api/maintenance/reasons")
    assert reasons.status_code == 200
    reason = next(item for item in reasons.json() if item["name"] == "Screen")

    created = await api.client.post(
        "/api/maintenance/cases",
        json={"serial": "SN-11", "reason_id": reason["id"]},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["maintenance_state"] == "with_it"
    assert body["device_model"] == "ThinkPad T14"
    assert body["maintenance"]["diagnosis_category"] == "Screen"
    assert body["maintenance"]["received_date"] is not None
    operations = {item["stage"]: item["status"] for item in body["stages"]}
    assert operations["received"] == "passed"
    assert operations["diagnosis"] == "passed"


async def test_phase06_create_rejects_unknown_serial(api: ApiHarness) -> None:
    response = await api.client.post(
        "/api/maintenance/cases", json={"serial": "SN-DOES-NOT-EXIST"}
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "Serial not found in Snipe-IT"


async def test_phase06_create_rejects_a_second_active_case(api: ApiHarness) -> None:
    first = await api.client.post(
        "/api/maintenance/cases", json={"serial": "SN-10"}
    )
    assert first.status_code == 201, first.text
    second = await api.client.post(
        "/api/maintenance/cases", json={"serial": "SN-10"}
    )
    assert second.status_code == 409, second.text
    detail = second.json()["detail"]
    assert detail["case_id"] == first.json()["id"]


async def test_phase06_other_reason_requires_details(api: ApiHarness) -> None:
    reasons = await api.client.get("/api/maintenance/reasons")
    other = next(item for item in reasons.json() if item["name"] == "Other")
    response = await api.client.post(
        "/api/maintenance/cases",
        json={"serial": "SN-10", "reason_id": other["id"]},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "Details are required for Other."


async def test_phase06_reasons_are_ordered_with_other_last(api: ApiHarness) -> None:
    response = await api.client.get("/api/maintenance/reasons")
    assert response.status_code == 200
    names = [item["name"] for item in response.json()]
    assert names[0] == "Screen"
    assert names[-1] == "Other"
    assert "Charger / power" in names


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


async def test_registration_details_include_priority_and_return_costs(
    api: ApiHarness,
) -> None:
    created = await _create(api, serial="SN-MAINT-DETAILS", kind="maintenance")
    response = await api.client.post(
        f"/api/handovers/{created['id']}/maintenance",
        json={
            "reported_issue": "Battery drains while asleep",
            "diagnosis_category": "Battery",
            "diagnosis_note": "Employee observed this after the last update.",
            "priority": "high",
            "cost": "180",
            "warranty": "no",
        },
    )
    assert response.status_code == 200, response.text
    maintenance = response.json()["maintenance"]
    assert maintenance["reported_issue"] == "Battery drains while asleep"
    assert maintenance["priority"] == "high"
    assert maintenance["diagnosis_note"].startswith("Employee observed")
    assert maintenance["cost"] == "180"
    assert maintenance["warranty"] == "no"


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
