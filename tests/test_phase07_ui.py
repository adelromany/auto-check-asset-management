"""Phase 07 maintenance UI page contracts."""

from __future__ import annotations

from tests.test_handovers_api import ApiHarness, api  # noqa: F401


async def test_maintenance_dashboard_and_devices_pages_render(api: ApiHarness) -> None:
    dashboard = await api.client.get("/maintenance")
    assert dashboard.status_code == 200, dashboard.text
    assert "Needs maintenance" in dashboard.text
    assert "In maintenance" in dashboard.text
    assert "Devices in maintenance" in dashboard.text

    devices = await api.client.get("/maintenance/devices")
    assert devices.status_code == 200, devices.text
    assert "Add device" in devices.text
    assert "With IT" in devices.text
    assert "At vendor" in devices.text


async def test_compact_maintenance_case_page_renders(api: ApiHarness) -> None:
    reasons = await api.client.get("/api/maintenance/reasons")
    reason_id = reasons.json()[0]["id"]
    created = await api.client.post(
        "/api/maintenance/cases",
        json={"serial": "SN-11", "reason_id": reason_id},
    )
    assert created.status_code == 201, created.text

    page = await api.client.get(f"/maintenance/{created.json()['id']}")
    assert page.status_code == 200, page.text
    assert "SN-11" in page.text
    assert "Set Maintenance" in page.text
    assert "History" in page.text
