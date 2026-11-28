from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.domain.catalog import Operation
from app.domain.stages import StageStatus
from app.services.device_history import build_cards
from tests.test_handovers_api import ApiHarness, _create
from tests.test_handovers_api import api as _api_fixture

api = _api_fixture  # reuse the API harness fixture from test_handovers_api


NOW = datetime(2026, 11, 28, 9, 0, tzinfo=timezone.utc)  # fixed: no clock ties between cases


def _case(kind="handover", status="in_progress", mode="snipeit", days=0):
    now = NOW
    info = None
    if kind == "maintenance":
        info = SimpleNamespace(
            received_date=date.today() - timedelta(days=days), sent_date=None, returned_date=None,
            diagnosis_category="Screen", reason_text=None,
            destination=SimpleNamespace(name="FixTech"),
        )
    return SimpleNamespace(
        id=uuid4(), kind=kind, status=status, recipient_mode=mode,
        created_at=now - timedelta(days=days), updated_at=now,
        device_company="B.tech", device_holder_name=None,
        recipient_snipeit_name="Alice", recipient_free_name=None, recipient_company="B.tech",
        engineer_name="Engineer", maintenance_state="with_it", maintenance=info,
        stages=[SimpleNamespace(stage=operation, status=StageStatus.PENDING, reason=None, detail={}) for operation in (Operation.RECEIVED, Operation.DIAGNOSIS, Operation.SNIPEIT_STATUS, Operation.TAKEN_BACK, Operation.SENT_OUT, Operation.RETURNED, Operation.READY_STATUS) if kind == "maintenance"],
    )


def test_cards_are_milestones_newest_first_without_cancelled() -> None:
    complete = _case(status="completed")
    complete.stages = [SimpleNamespace(stage=op, status=StageStatus.PASSED, reason=None, detail={}) for op in Operation]
    opened = _case()
    repair = _case("maintenance", days=10)
    repair.maintenance.sent_date = date.today() - timedelta(days=5)
    repair.maintenance.returned_date = date.today()
    cancelled = _case("maintenance", status="cancelled", days=3)
    cards = build_cards([complete, opened, repair, cancelled])
    assert [card["headline"].split(" -")[0] for card in cards] == [
        "Returned from FixTech", "Handed over to Alice", "Handover in progress",
        "Dispatched to FixTech", "Received for maintenance",
    ]
    assert len(cards) == 5
    assert cards[0]["facts"][-1]["value"] == "10"
    assert all("print" not in card["headline"].lower() for card in cards)


async def test_history_api_and_unknown_serial(api: ApiHarness) -> None:
    case = await _create(api, serial="SN-10")
    response = await api.client.get("/api/devices/SN-10/history")
    assert response.status_code == 200, response.text
    assert response.json()["cards"][0]["case_url"] == f"/handovers/{case['id']}"
    assert response.json()["cards"][0]["headline"] == "Handover in progress"
    empty = await api.client.get("/api/devices/UNKNOWN/history")
    assert empty.status_code == 200 and empty.json()["cards"] == []
    search = await api.client.get("/api/devices", params={"q": "ThinkPad"})
    assert any(item["serial"] == "SN-10" for item in search.json()["items"])


def test_device_place_kinds() -> None:
    from app.services.device_history import device_place

    in_progress = _case()
    held = _case()
    held.device_holder_name = "Alice"
    repair = _case("maintenance")
    at_vendor = _case("maintenance")
    at_vendor.maintenance_state = "at_vendor"
    cancelled = _case(status="cancelled")
    ready = _case(mode="none")
    ready.stages = [SimpleNamespace(stage=op, status=StageStatus.PASSED, reason=None, detail={}) for op in Operation]

    assert device_place(in_progress) == ("With IT", "lab")
    assert device_place(held) == ("With Alice", "user")
    assert device_place(repair) == ("With IT", "maintenance")
    assert device_place(at_vendor) == ("At vendor FixTech", "maintenance")
    assert device_place(cancelled) == ("Unknown", "unknown")
    assert device_place(ready) == ("Ready lab", "lab")


async def test_device_list_filters_sorts_and_reports_filter_data(api: ApiHarness) -> None:
    await _create(api, serial="SN-10")  # B.tech, no holder -> lab
    await _create(api, serial="SN-11")  # held by Alice -> user
    await _create(api, serial="SN-REPAIR", kind="maintenance")

    everything = (await api.client.get("/api/devices")).json()
    assert everything["total"] == 3
    assert everything["companies"] == ["B.tech"]
    assert everything["counts"] == {"lab": 1, "user": 1, "maintenance": 1, "unknown": 0}
    kinds = {row["serial"]: row["place_kind"] for row in everything["items"]}
    assert kinds == {"SN-10": "lab", "SN-11": "user", "SN-REPAIR": "maintenance"}
    holder = next(row for row in everything["items"] if row["serial"] == "SN-11")
    assert holder["holder"] == "Alice"

    only_user = (await api.client.get("/api/devices", params={"place": "user"})).json()
    assert [row["serial"] for row in only_user["items"]] == ["SN-11"]
    assert only_user["total"] == 1
    assert only_user["counts"]["lab"] == 1  # counts ignore the place filter

    searched = (await api.client.get("/api/devices", params={"q": "sn-1", "place": "lab"})).json()
    assert [row["serial"] for row in searched["items"]] == ["SN-10"]

    newest = [row["serial"] for row in (await api.client.get("/api/devices", params={"order": "desc"})).json()["items"]]
    oldest = [row["serial"] for row in (await api.client.get("/api/devices", params={"order": "asc"})).json()["items"]]
    assert newest == list(reversed(oldest))

    assert (await api.client.get("/api/devices", params={"place": "nope"})).status_code == 422
    assert (await api.client.get("/api/devices", params={"order": "sideways"})).status_code == 422


async def test_device_company_filter_uses_exact_company(api: ApiHarness) -> None:
    await _create(api, serial="SN-10")
    await _create(api, serial="SN-11")
    found = (await api.client.get("/api/devices", params={"company": "B.tech"})).json()
    assert [row["serial"] for row in found["items"]] == ["SN-10"]
    assert (await api.client.get("/api/devices", params={"company": "Mylo"})).json()["total"] == 0


async def test_device_pages_render_the_new_shells(api: ApiHarness, monkeypatch) -> None:
    from app import config

    monkeypatch.setattr(config, "SSO_ENABLED", False)
    listing = (await api.client.get("/devices")).text
    for marker in ("data-device-search", "data-device-company", "data-place-chips", "data-sort-last", "data-device-total"):
        assert marker in listing
    detail = (await api.client.get("/devices/SN-10")).text
    for marker in ("data-device-summary", "data-live-holder", "data-new-handover", "data-new-maintenance", "data-device-history"):
        assert marker in detail
