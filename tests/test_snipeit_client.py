"""Phase 3 client tests against the stateful Snipe-IT fake."""

from __future__ import annotations

import logging

import httpx
import pytest
import pytest_asyncio

import app.clients.snipeit as snipeit
from tests.fakes.snipeit_fake import SnipeItFake

BASE_URL = "http://snipeit.test"


@pytest_asyncio.fixture()
async def fake() -> SnipeItFake:
    return SnipeItFake()


@pytest_asyncio.fixture()
async def client(fake: SnipeItFake):
    async with httpx.AsyncClient(transport=fake.transport) as http_client:
        yield snipeit.SnipeItClient(
            BASE_URL,
            snipeit.ServiceAccountProvider(fake.token),
            http_client=http_client,
            engineer_email="engineer@example.com",
            retry_backoff=0.0,
        )


async def test_find_user_by_exact_username(client: snipeit.SnipeItClient) -> None:
    user = await client.find_user("alice")
    assert user is not None
    assert user.id == 1
    assert user.username == "alice"


async def test_find_user_by_exact_email(client: snipeit.SnipeItClient) -> None:
    user = await client.find_user("bob@example.com")
    assert user is not None
    assert user.id == 2
    assert user.email == "bob@example.com"


async def test_find_user_falls_back_to_first_match(
    client: snipeit.SnipeItClient,
) -> None:
    user = await client.find_user("example")
    assert user is not None
    assert user.id == 1


async def test_find_user_returns_none_when_no_rows(
    client: snipeit.SnipeItClient,
) -> None:
    assert await client.find_user("nobody-here") is None


async def test_get_user_happy_path(client: snipeit.SnipeItClient) -> None:
    user = await client.get_user(2)
    assert user.name == "Bob"


async def test_get_user_not_found(client: snipeit.SnipeItClient) -> None:
    with pytest.raises(snipeit.SnipeItNotFound):
        await client.get_user(999)


async def test_list_user_assets(client: snipeit.SnipeItClient) -> None:
    assets = await client.list_user_assets(1)
    assert [asset.id for asset in assets] == [11]
    assert assets[0].assigned_to_id == 1


async def test_get_asset_by_serial_exact_match(
    client: snipeit.SnipeItClient,
) -> None:
    asset = await client.get_asset_by_serial("SN-10")
    assert asset.id == 10
    assert asset.asset_tag == "A-10"
    assert asset.status == "Ready"
    assert asset.model == "ThinkPad T14"
    assert asset.category == "Laptops"
    assert asset.manufacturer == "Lenovo"
    assert asset.location == "HQ"
    assert asset.purchase_date == "2024-01-01"
    assert asset.warranty_months == 36


async def test_get_asset_by_serial_falls_back_to_first_row(
    client: snipeit.SnipeItClient,
) -> None:
    asset = await client.get_asset_by_serial("SN-1")
    assert asset.id == 10


async def test_get_asset_by_serial_not_found(
    client: snipeit.SnipeItClient,
) -> None:
    with pytest.raises(snipeit.SnipeItNotFound):
        await client.get_asset_by_serial("ZZZ-999")


async def test_get_asset_happy_path(client: snipeit.SnipeItClient) -> None:
    asset = await client.get_asset(11)
    assert asset.serial == "SN-11"
    assert asset.assigned_to_id == 1


async def test_checkout_asset_to_user(client: snipeit.SnipeItClient) -> None:
    result = await client.checkout_asset_to_user(10, 1, "Handover by engineer")
    assert result.status == "success"
    assert result.message == "Checked out"

    asset = await client.get_asset(10)
    assert asset.assigned_to_id == 1
    assert asset.assigned_to_name == "Alice"


async def test_checkin_asset(client: snipeit.SnipeItClient) -> None:
    result = await client.checkin_asset(11, "Returned")
    assert result.status == "success"

    asset = await client.get_asset(11)
    assert asset.assigned_to_id is None


async def test_upload_and_list_asset_files(client: snipeit.SnipeItClient) -> None:
    content = b"%PDF-1.4 signed sheet"
    result = await client.upload_asset_file(
        10, "scan.pdf", content, "application/pdf", "Handover scan"
    )
    assert result.status == "success"

    files = await client.list_asset_files(10)
    assert len(files) == 1
    assert files[0].filename == "scan.pdf"
    assert files[0].size == len(content)


async def test_whoami(client: snipeit.SnipeItClient) -> None:
    user = await client.whoami()
    assert user.id == 1
    assert user.username == "alice"


async def test_auth_error_does_not_leak_the_token(
    fake: SnipeItFake, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    async with httpx.AsyncClient(transport=fake.transport) as http_client:
        client = snipeit.SnipeItClient(
            BASE_URL,
            snipeit.ServiceAccountProvider("super-secret-token"),
            http_client=http_client,
        )
        with pytest.raises(snipeit.SnipeItAuthError) as error:
            await client.whoami()

    assert error.value.status_code == 401
    assert "super-secret-token" not in str(error.value)
    assert "super-secret-token" not in caplog.text


async def test_403_is_an_auth_error() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(403, json={"status": "error"})
    )
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = snipeit.SnipeItClient(
            BASE_URL,
            snipeit.ServiceAccountProvider("token"),
            http_client=http_client,
        )
        with pytest.raises(snipeit.SnipeItAuthError) as error:
            await client.whoami()
    assert error.value.status_code == 403


async def test_404_is_not_found() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(404, json={"status": "error"})
    )
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = snipeit.SnipeItClient(
            BASE_URL,
            snipeit.ServiceAccountProvider("token"),
            http_client=http_client,
        )
        with pytest.raises(snipeit.SnipeItNotFound):
            await client.get_user(1)


async def test_get_retries_twice_then_succeeds(
    fake: SnipeItFake, client: snipeit.SnipeItClient
) -> None:
    fake.fail_get_statuses = [500, 500]

    user = await client.whoami()

    assert user.id == 1
    assert len([call for call in fake.calls if call[0] == "GET"]) == 3


async def test_get_stops_after_two_retries(
    fake: SnipeItFake, client: snipeit.SnipeItClient
) -> None:
    fake.fail_get_statuses = [500, 500, 500]

    with pytest.raises(snipeit.SnipeItRejected) as error:
        await client.whoami()

    assert error.value.status_code == 500
    assert len([call for call in fake.calls if call[0] == "GET"]) == 3


async def test_post_is_never_retried(
    fake: SnipeItFake, client: snipeit.SnipeItClient
) -> None:
    fake.fail_post_statuses = [500]

    with pytest.raises(snipeit.SnipeItRejected):
        await client.checkin_asset(10, "note")

    assert len(fake.write_calls()) == 1


async def test_get_network_error_is_retried_then_unavailable() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("down", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        client = snipeit.SnipeItClient(
            BASE_URL,
            snipeit.ServiceAccountProvider("token"),
            http_client=http_client,
            retry_backoff=0.0,
        )
        with pytest.raises(snipeit.SnipeItUnavailable):
            await client.whoami()

    assert len(calls) == 3


async def test_post_network_error_is_not_retried() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("down", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        client = snipeit.SnipeItClient(
            BASE_URL,
            snipeit.ServiceAccountProvider("token"),
            http_client=http_client,
            retry_backoff=0.0,
        )
        with pytest.raises(snipeit.SnipeItUnavailable):
            await client.checkin_asset(10, "note")

    assert len(calls) == 1


async def test_missing_token_raises_auth_error() -> None:
    client = snipeit.SnipeItClient(BASE_URL, snipeit.ServiceAccountProvider(""))
    try:
        with pytest.raises(snipeit.SnipeItAuthError) as error:
            await client.whoami()
    finally:
        await client.aclose()

    assert error.value.status_code == 503


async def test_invalid_json_is_rejected() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"not-json")
    )
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = snipeit.SnipeItClient(
            BASE_URL,
            snipeit.ServiceAccountProvider("token"),
            http_client=http_client,
        )
        with pytest.raises(snipeit.SnipeItRejected):
            await client.whoami()
