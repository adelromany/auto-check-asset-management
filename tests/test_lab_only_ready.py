"""Round 3: a Lab-only case on a device that is already Ready must reach READY.

Regression for the acceptance report "Lab-only case stays Not complete": the
Device status part could only pass when the engineer *changed* the status, so a
device that was already "Ready to deploy" never satisfied it.
"""

from __future__ import annotations

from tests.test_handovers_api import ApiHarness, _create
from tests.test_handovers_api import api as _api_fixture

api = _api_fixture  # reuse the API harness fixture from test_handovers_api

REPORT = {
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
}


async def _submit_report(api: ApiHarness, serial: str, handover_id: str) -> None:
    session = await api.client.get(f"/api/session/new?handover_id={handover_id}")
    code = session.json()["code"]
    submit = await api.client.post(
        f"/api/session/{code}/submit", json={"serial": serial, **REPORT}
    )
    assert submit.status_code == 200, submit.text


def _stage(body: dict, name: str) -> dict:
    return next(item for item in body["stages"] if item["stage"] == name)


async def _ids(api: ApiHarness, query: str) -> list[str]:
    response = await api.client.get(f"/api/handovers?{query}")
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


async def test_lab_only_on_ready_device_reaches_ready_and_is_listed(
    api: ApiHarness,
) -> None:
    created = await _create(api, serial="SN-10", mode="none")
    handover_id = created["id"]

    # Device status passed on its own: the device is already Ready to deploy.
    detail = (await api.client.get(f"/api/handovers/{handover_id}")).json()
    assert _stage(detail, "device_status")["status"] == "passed"
    assert detail["outcome"] == "not_complete"
    assert handover_id in await _ids(api, "outcome=not_complete")

    await _submit_report(api, "SN-10", handover_id)

    detail = (await api.client.get(f"/api/handovers/{handover_id}")).json()
    assert _stage(detail, "agent_report")["status"] == "passed"
    assert _stage(detail, "software_check")["status"] == "passed"
    # Non-required parts are still pending and must not hold the case back.
    assert _stage(detail, "checkout")["status"] == "pending"
    assert detail["outcome"] == "ready"
    assert detail["status"] == "ready"
    assert handover_id in await _ids(api, "outcome=ready")
    assert handover_id not in await _ids(api, "outcome=not_complete")


async def test_confirm_status_with_no_label_passes_when_already_ready(
    api: ApiHarness,
) -> None:
    api.fake.assets[10]["status_label"] = {"id": 2, "name": "Maintenance"}
    created = await _create(api, serial="SN-10", mode="none")
    handover_id = created["id"]
    detail = (await api.client.get(f"/api/handovers/{handover_id}")).json()
    assert _stage(detail, "device_status")["status"] == "pending"

    # Someone fixes the status in Snipe-IT; the engineer presses "Confirm status".
    api.fake.assets[10]["status_label"] = {"id": 1, "name": "Ready to deploy"}
    response = await api.client.post(
        f"/api/handovers/{handover_id}/device-status",
        json={"status_label_id": None},
    )

    assert response.status_code == 200, response.text
    stage = _stage(response.json(), "device_status")
    assert stage["status"] == "passed"
    assert response.json()["snipeit_status_name"] == "Ready to deploy"


async def test_confirm_status_with_no_label_fails_when_not_ready(
    api: ApiHarness,
) -> None:
    api.fake.assets[10]["status_label"] = {"id": 2, "name": "Maintenance"}
    created = await _create(api, serial="SN-10", mode="none")

    response = await api.client.post(
        f"/api/handovers/{created['id']}/device-status",
        json={"status_label_id": None},
    )

    stage = _stage(response.json(), "device_status")
    assert stage["status"] == "failed"
    assert stage["reason"] == "Status is Maintenance"


async def test_reading_the_live_device_passes_status_once_it_is_ready(
    api: ApiHarness,
) -> None:
    api.fake.assets[10]["status_label"] = {"id": 2, "name": "Maintenance"}
    created = await _create(api, serial="SN-10", mode="none")
    handover_id = created["id"]
    api.fake.assets[10]["status_label"] = {"id": 1, "name": "Ready to deploy"}

    live = await api.client.get(f"/api/handovers/{handover_id}/device-live")
    assert live.status_code == 200, live.text

    detail = (await api.client.get(f"/api/handovers/{handover_id}")).json()
    assert _stage(detail, "device_status")["status"] == "passed"
    # Reading again is idempotent: no second operation event.
    await api.client.get(f"/api/handovers/{handover_id}/device-live")
    events = (await api.client.get(f"/api/handovers/{handover_id}")).json()["events"]
    recorded = [e for e in events if e["type"] == "operation_recorded"]
    assert len(recorded) == 1


async def test_a_device_that_is_not_ready_is_never_auto_passed(
    api: ApiHarness,
) -> None:
    api.fake.assets[10]["status_label"] = {"id": 2, "name": "Maintenance"}
    created = await _create(api, serial="SN-10", mode="none")

    await api.client.get(f"/api/handovers/{created['id']}/device-live")

    detail = (await api.client.get(f"/api/handovers/{created['id']}")).json()
    assert _stage(detail, "device_status")["status"] == "pending"
