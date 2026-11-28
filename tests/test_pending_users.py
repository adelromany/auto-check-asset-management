from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import pending_users
from app.services.pending_users import username_from_device
from tests.test_handovers_api import ApiHarness, _create, api


@pytest.mark.parametrize("raw,expected", [(r"CORP\ali.hassan", "ali.hassan"), (r"AzureAD\Ali Hassan", "Ali Hassan"), ("ali.hassan", "ali.hassan")])
def test_username_from_device(raw, expected):
    assert username_from_device(raw) == expected


async def test_pending_found_by_username_links_and_checks_out(api: ApiHarness) -> None:
    case = await _create(api, serial="SN-10")
    response = await api.client.post(f"/api/handovers/{case['id']}/recipient", json={"mode": "pending_user", "username": "alice", "employee_code": "EMP-1"})
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "snipeit"
    assert response.json()["recipient_snipeit_id"] == 1
    assert response.json()["pending_found_at"] is not None
    assert any(event["type"] == "pending_user_found" for event in response.json()["events"])
    assert next(stage for stage in response.json()["stages"] if stage["stage"] == "checkout")["status"] == "passed"


async def test_pending_found_by_employee_code(api: ApiHarness) -> None:
    api.fake.users[1]["employee_num"] = "EMP-TEST-1"
    case = await _create(api, serial="SN-10")
    response = await api.client.post(f"/api/handovers/{case['id']}/recipient", json={"mode": "pending_user", "employee_code": "EMP-TEST-1"})
    assert response.json()["recipient_snipeit_id"] == 1


async def test_company_mismatch_links_without_automatic_checkout(api: ApiHarness) -> None:
    api.fake.users[1]["company"]["name"] = "Mylo"
    case = await _create(api, serial="SN-10")
    response = await api.client.post(f"/api/handovers/{case['id']}/recipient", json={"mode": "pending_user", "username": "alice"})
    assert response.json()["recipient_snipeit_id"] == 1
    assert "company_mismatch" in [warning["code"] for warning in response.json()["warnings"]]
    assert next(stage for stage in response.json()["stages"] if stage["stage"] == "checkout")["status"] != "passed"


async def test_not_found_only_updates_check_time(api: ApiHarness) -> None:
    case = await _create(api, serial="SN-10")
    response = await api.client.post(f"/api/handovers/{case['id']}/recipient", json={"mode": "pending_user", "username": "nobody"})
    assert response.json()["mode"] == "pending_user"
    assert response.json()["pending_checked_at"] is not None
    assert response.json()["pending_found_at"] is None
    recipient = next(stage for stage in response.json()["stages"] if stage["stage"] == "recipient_check")
    assert recipient["status"] == "not_done"
    assert recipient["reason"] == "User not in Snipe-IT yet"


async def test_pending_requires_code_or_username(api: ApiHarness) -> None:
    case = await _create(api, serial="SN-10")
    response = await api.client.post(f"/api/handovers/{case['id']}/recipient", json={"mode": "pending_user"})
    assert response.status_code == 422


async def test_ambiguous_employee_code_does_not_link(api: ApiHarness) -> None:
    api.fake.users[1]["employee_num"] = "EMP-DUP"
    api.fake.users[2]["employee_num"] = "EMP-DUP"
    case = await _create(api, serial="SN-10")
    response = await api.client.post(
        f"/api/handovers/{case['id']}/recipient",
        json={"mode": "pending_user", "employee_code": "EMP-DUP"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "pending_user"
    assert response.json()["recipient_snipeit_id"] is None
    assert any(event["type"] == "pending_ambiguous" for event in response.json()["events"])


async def test_batch_survives_one_case_error(monkeypatch) -> None:
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalars.return_value = iter([1, 2])
    calls = []

    async def check(session, case_id, **kwargs):
        calls.append(case_id)
        if case_id == 1:
            raise RuntimeError("one failed")
        return case_id

    monkeypatch.setattr(pending_users, "check_pending_user", check)
    results = await pending_users.check_pending_users(session, object())
    assert calls == [1, 2]
    assert results == [2]
    session.rollback.assert_awaited_once()
