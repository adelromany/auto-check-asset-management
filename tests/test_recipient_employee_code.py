"""Round 3: recipient search by employee code and the device-holder quick fill."""

from __future__ import annotations

import httpx
import pytest

from app.clients import snipeit
from app.domain.recipient_identity import looks_like_employee_code
from tests.test_handovers_api import ApiHarness, _create
from tests.test_handovers_api import api as _api_fixture

api = _api_fixture  # reuse the API harness fixture from test_handovers_api


@pytest.mark.parametrize("text", ["12345", "EMP1234", "bl0042", " 99 ", "AB12"])
def test_employee_code_shapes(text: str) -> None:
    assert looks_like_employee_code(text) is True


@pytest.mark.parametrize("text", ["", None, "alice", "a1", "7", "ABCDE123", "john.doe", "12 34", "alice2x"])
def test_names_and_other_text_are_not_employee_codes(text) -> None:
    assert looks_like_employee_code(text) is False


def _user(user_id: int, name: str, code: str | None) -> dict:
    return {
        "id": user_id, "username": name.lower(), "name": name,
        "email": f"{name.lower()}@example.com", "employee_num": code,
        "company": {"id": 3, "name": "B.tech"},
    }


def _client(handler) -> snipeit.SnipeItClient:
    return snipeit.SnipeItClient(
        "http://snipeit.test",
        snipeit.ServiceAccountProvider("token"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_backoff=0.0,
    )


async def test_client_uses_the_employee_num_filter_and_keeps_exact_matches_only() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"rows": [_user(1, "Wide", "123456"), _user(2, "Exact", "12345")]})

    user = await _client(handler).find_user_by_employee_num(" 12345 ")

    assert user is not None and user.id == 2 and user.employee_num == "12345"
    assert seen[0]["employee_num"] == "12345"


async def test_client_falls_back_to_search_when_the_filter_is_ignored() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append(params)
        if "employee_num" in params:
            return httpx.Response(200, json={"rows": []})  # filter ignored / nothing
        return httpx.Response(200, json={"rows": [_user(7, "Seven", "ab777")]})

    user = await _client(handler).find_user_by_employee_num("AB777")

    assert user is not None and user.id == 7  # case-insensitive exact match
    assert "employee_num" in calls[0] and "search" in calls[1]


async def test_client_returns_none_for_a_partial_or_blank_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rows": [_user(1, "Wide", "123456")]})

    client = _client(handler)
    assert await client.find_user_by_employee_num("12345") is None
    assert await client.find_user_by_employee_num("  ") is None


async def test_search_puts_the_exact_employee_code_on_top_and_shows_it(api: ApiHarness) -> None:
    api.fake.users[3] = _user(3, "Longer", "123456")
    api.fake.users[4] = _user(4, "Exact", "12345")
    case = await _create(api, serial="SN-1")

    response = await api.client.get(
        "/api/snipeit/users", params={"q": "12345", "handover_id": case["id"]}
    )

    assert response.status_code == 200, response.text
    rows = response.json()
    assert [row["id"] for row in rows] == [4, 3]
    assert rows[0]["employee_num"] == "12345"


async def test_a_name_search_is_unchanged(api: ApiHarness) -> None:
    api.fake.users[3] = _user(3, "Carol", "555")
    case = await _create(api, serial="SN-1")

    response = await api.client.get(
        "/api/snipeit/users", params={"q": "carol", "handover_id": case["id"]}
    )

    assert [row["id"] for row in response.json()] == [3]


async def test_holder_quick_fill_loads_exactly_that_user(api: ApiHarness) -> None:
    case = await _create(api, serial="SN-11")  # held by Alice (id 1)
    detail = (await api.client.get(f"/api/handovers/{case['id']}")).json()
    assert detail["device_holder_id"] == 1

    response = await api.client.get(
        "/api/snipeit/users",
        params={"user_id": detail["device_holder_id"], "handover_id": case["id"]},
    )

    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == [1]
    assert response.json()[0]["name"] == "Alice"


async def test_users_endpoint_needs_a_query_or_a_user_id(api: ApiHarness) -> None:
    case = await _create(api, serial="SN-1")

    response = await api.client.get("/api/snipeit/users", params={"handover_id": case["id"]})

    assert response.status_code == 422


async def test_recipient_search_endpoint_returns_employee_num_in_the_dto(api: ApiHarness) -> None:
    api.fake.users[4] = _user(4, "Exact", "12345")
    case = await _create(api, serial="SN-1")

    response = await api.client.post(
        f"/api/handovers/{case['id']}/recipient/search", params={"q": "12345"}
    )

    assert response.status_code == 200, response.text
    candidates = response.json()["candidates"]
    assert candidates[0]["id"] == 4
    assert candidates[0]["employee_num"] == "12345"


async def test_pending_user_check_finds_the_user_by_employee_code(api: ApiHarness) -> None:
    api.fake.users[4] = _user(4, "Newhire", "20077")
    case = await _create(api, serial="SN-1", mode="pending_user")

    response = await api.client.post(
        f"/api/handovers/{case['id']}/recipient",
        json={"mode": "pending_user", "employee_code": "20077", "username": "someone-else"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recipient_snipeit_id"] == 4


async def test_client_reports_every_exact_match_so_duplicates_stay_ambiguous() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rows": [_user(1, "One", "DUP-1"), _user(2, "Two", "DUP-1")]})

    users = await _client(handler).find_users_by_employee_num("dup-1")

    assert [user.id for user in users] == [1, 2]
