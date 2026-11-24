"""Live tests against a real Snipe-IT development instance.

Skipped unless ``SNIPEIT_LIVE_TEST=1`` (or ``SNIPEIT_LIVE=1``). These tests
are the only place in the suite allowed to touch a real API. They refuse to
modify anything whose name, username or serial does not start with ``TEST-``.

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
from pathlib import Path

import httpx
import pytest

import app.clients.snipeit as snipeit

_LIVE = os.getenv("SNIPEIT_LIVE_TEST") == "1" or os.getenv("SNIPEIT_LIVE") == "1"
if _LIVE:
    # Live runs read the developer .env; normal test runs never do.
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _LIVE,
        reason="set SNIPEIT_LIVE_TEST=1 (or SNIPEIT_LIVE=1) to run against a real Snipe-IT",
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


# -- V2 live checks (Phase 01 step 1.6) ------------------------------------


async def test_v2_asset_has_company_model_and_status(
    client: snipeit.SnipeItClient,
) -> None:
    asset = await client.get_asset_by_serial("TEST-SN-0001")
    assert asset.company == "B.tech"
    assert asset.company_id is not None
    assert asset.model
    assert asset.category
    assert asset.status
    assert asset.status_id is not None


async def test_v2_status_update_roundtrip(
    client: snipeit.SnipeItClient,
) -> None:
    asset = await client.get_asset_by_serial("TEST-SN-0001")
    maintenance = await client.find_status_label_id("Maintenance")
    ready = await client.find_status_label_id("Ready to deploy")
    assert maintenance is not None and ready is not None
    try:
        await client.update_asset_status(asset.id, maintenance)
        changed = await client.get_asset(asset.id)
        assert (changed.status or "").casefold() == "maintenance"
    finally:
        await client.update_asset_status(asset.id, ready)
    restored = await client.get_asset(asset.id)
    assert (restored.status or "").casefold() == "ready to deploy"


async def test_v2_search_users_return_company(
    client: snipeit.SnipeItClient,
) -> None:
    users = await client.search_users("test.btech")
    assert users
    assert all(user.company for user in users)


async def test_v2_checkout_sets_deployed_then_checks_in(
    client: snipeit.SnipeItClient,
) -> None:
    asset = await client.get_asset_by_serial("TEST-SN-0001")
    user = await client.find_user("test.btech1")
    deployed = await client.find_status_label_id("Deployed")
    ready = await client.find_status_label_id("Ready to deploy")
    assert user is not None and deployed is not None and ready is not None
    if asset.assigned_to_id is not None:
        await client.checkin_asset(asset.id, "TEST- live v2 precondition")
    try:
        result = await client.checkout_asset_to_user(
            asset.id, user.id, "TEST- live v2 checkout", status_id=deployed
        )
        assert result.status == "success"
        checked_out = await client.get_asset(asset.id)
        assert checked_out.assigned_to_id == user.id
        assert (checked_out.status or "").casefold() == "deployed"
    finally:
        await client.checkin_asset(asset.id, "TEST- live v2 checkin")
        await client.update_asset_status(asset.id, ready)
    checked_in = await client.get_asset(asset.id)
    assert checked_in.assigned_to_id is None
