"""Reset only the V2 TEST-SN-* fixtures in the Snipe-IT dev instance.

The helper is deliberately narrow: it refuses assets whose serial does not
start with ``TEST-SN-``. It restores the seeded fixture state expected by the
live probes: all assets are Ready to deploy and unassigned, except
TEST-SN-0005 which belongs to test.btech2.

    python tools/snipeit_reset_tests.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.clients.snipeit import ServiceAccountProvider, SnipeItClient  # noqa: E402

SERIALS = (
    "TEST-SN-0001",
    "TEST-SN-0002",
    "TEST-SN-0003",
    "TEST-SN-0004",
    "TEST-SN-0005",
)
SEEDED_OWNER = {"TEST-SN-0005": "test.btech2"}


async def reset() -> int:
    base_url = os.getenv("SNIPEIT_URL", "").rstrip("/")
    token = os.getenv("SNIPEIT_TOKEN", "")
    if not base_url or not token:
        raise SystemExit("SNIPEIT_URL and SNIPEIT_TOKEN must be set (see .env).")

    client = SnipeItClient(base_url, ServiceAccountProvider(token))
    failed = False
    try:
        ready_id = await client.find_status_label_id("Ready to deploy")
        if ready_id is None:
            raise SystemExit('Status label "Ready to deploy" not found.')
        deployed_id = await client.find_status_label_id("Deployed")
        for serial in SERIALS:
            asset = await client.get_asset_by_serial(serial)
            if not asset.serial or not asset.serial.startswith("TEST-SN-"):
                raise RuntimeError(f"refusing to reset non-test asset {asset.id}")
            if asset.assigned_to_id is not None:
                await client.checkin_asset(asset.id, "V2 verification reset")
            await client.update_asset_status(asset.id, ready_id)

            owner = SEEDED_OWNER.get(serial)
            if owner:
                users = await client.search_users(owner)
                user = next((item for item in users if item.username == owner), None)
                if user is None:
                    raise RuntimeError(f"seed user {owner} not found")
                await client.checkout_asset_to_user(
                    asset.id,
                    user.id,
                    "V2 verification seeded recipient fixture",
                    status_id=deployed_id,
                )
            print(f"reset {serial} -> Ready to deploy")
    except Exception as exc:  # noqa: BLE001
        failed = True
        print(f"FAIL reset: {type(exc).__name__}: {exc}")
    finally:
        await client.aclose()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(reset()))
