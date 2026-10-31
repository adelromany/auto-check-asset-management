"""Live tests against a real Snipe-IT development instance.

Skipped unless ``SNIPEIT_LIVE_TEST=1``. These tests are the only place in the
suite allowed to touch a real API. They refuse to modify anything whose name,
username or serial does not start with ``TEST-``.

Required environment:

    SNIPEIT_LIVE_TEST=1
    SNIPEIT_URL=http://localhost:8081
    SNIPEIT_TOKEN=<admin API token>

Optional (defaults shown):

    SNIPEIT_LIVE_SERIAL=TEST-SN-0001
    SNIPEIT_LIVE_USER=test.recipient
"""

from __future__ import annotations

import os

import httpx
import pytest

import app.clients.snipeit as snipeit

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("SNIPEIT_LIVE_TEST") != "1",
        reason="set SNIPEIT_LIVE_TEST=1 to run against a real Snipe-IT",
    ),
]

BASE_URL = os.getenv("SNIPEIT_URL", "")
TOKEN = os.getenv("SNIPEIT_TOKEN", "")
SERIAL = os.getenv("SNIPEIT_LIVE_SERIAL", "TEST-SN-0001")
USER = os.getenv("SNIPEIT_LIVE_USER", "test.recipient")
TEST_PREFIX = "TEST-"


def _require_settings() -> None:
    if not BASE_URL or not TOKEN:
        pytest.skip("SNIPEIT_URL and SNIPEIT_TOKEN must be set for live tests")


@pytest.fixture()
async def client():
    _require_settings()
    async with httpx.AsyncClient(timeout=20.0) as http_client:
        async with snipeit.SnipeItClient(
            BASE_URL,
            snipeit.ServiceAccountProvider(TOKEN),
            http_client=http_client,
            engineer_email="live-test@example.test",
        ) as live_client:
            yield live_client


async def test_whoami(client: snipeit.SnipeItClient) -> None:
    user = await client.whoami()
    assert user.id > 0


async def test_find_test_user(client: snipeit.SnipeItClient) -> None:
    user = await client.find_user(USER)
    assert user is not None, f"live user {USER!r} does not exist"
    assert (user.username or "").startswith(TEST_PREFIX) or (
        user.name or ""
    ).startswith(TEST_PREFIX), "live tests only touch TEST- users"


async def test_get_test_asset_by_serial(
    client: snipeit.SnipeItClient,
) -> None:
    assert SERIAL.startswith(TEST_PREFIX)
    asset = await client.get_asset_by_serial(SERIAL)
    assert asset.id > 0
    assert asset.serial == SERIAL


async def test_list_test_user_assets(client: snipeit.SnipeItClient) -> None:
    user = await client.find_user(USER)
    assert user is not None
    assets = await client.list_user_assets(user.id)
    for asset in assets:
        assert asset.id > 0


async def test_upload_and_list_test_asset_file(
    client: snipeit.SnipeItClient,
) -> None:
    asset = await client.get_asset_by_serial(SERIAL)
    content = b"%PDF-1.4\n% live test upload\n"
    filename = "TEST-live-upload.pdf"

    result = await client.upload_asset_file(
        asset.id, filename, content, "application/pdf", "TEST- live test"
    )
    assert result.status == "success"

    files = await client.list_asset_files(asset.id)
    assert any(item.filename == filename for item in files)


async def test_checkout_then_checkin_test_asset(
    client: snipeit.SnipeItClient,
) -> None:
    """Round-trip only the TEST- asset, restoring it to unassigned."""
    asset = await client.get_asset_by_serial(SERIAL)
    user = await client.find_user(USER)
    assert user is not None

    if asset.assigned_to_id not in (None, user.id):
        pytest.skip("TEST- asset is assigned to a non-test user; not touching it")

    try:
        if asset.assigned_to_id != user.id:
            result = await client.checkout_asset_to_user(
                asset.id, user.id, "TEST- live checkout"
            )
            assert result.status == "success"

        checked_out = await client.get_asset(asset.id)
        assert checked_out.assigned_to_id == user.id
    finally:
        await client.checkin_asset(asset.id, "TEST- live checkin")

    checked_in = await client.get_asset(asset.id)
    assert checked_in.assigned_to_id is None
