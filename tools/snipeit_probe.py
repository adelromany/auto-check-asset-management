"""Phase 01 probe: run the V2 Snipe-IT calls against the REAL dev instance.

Uses the app's own ``SnipeItClient``. Prints PASS/FAIL per check and writes a
short table to ``docs/snipeit-integration-report.md`` (no tokens, no secrets).

    python tools/snipeit_probe.py

Every check restores the seed state so the script can be re-run.
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

from app.clients.snipeit import (  # noqa: E402
    ServiceAccountProvider,
    SnipeItAuthError,
    SnipeItClient,
    SnipeItNotFound,
)

BASE_URL = os.getenv("SNIPEIT_URL", "").rstrip("/")
TOKEN = os.getenv("SNIPEIT_TOKEN", "")
REPORT = ROOT / "docs" / "snipeit-integration-report.md"
READY = "Ready to deploy"
MAINTENANCE = "Maintenance"

# 1x1 transparent PNG (small, stable bytes).
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c63600000020001e221bc33000000"
    "0049454e44ae426082"
)


class Probe:
    def __init__(self) -> None:
        if not BASE_URL or not TOKEN:
            raise SystemExit("SNIPEIT_URL and SNIPEIT_TOKEN must be set (see .env).")
        self.results: list[tuple[int, str, bool, str]] = []

    def record(self, number: int, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((number, name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'} {number:02d} {name}" + (f" :: {detail}" if detail and not ok else ""))

    async def check(self, number: int, name: str, fn) -> None:  # type: ignore[no-untyped-def]
        try:
            detail = await fn()
            self.record(number, name, True, detail or "")
        except AssertionError as exc:
            self.record(number, name, False, str(exc))
        except Exception as exc:  # noqa: BLE001 - report the real error
            self.record(number, name, False, f"{type(exc).__name__}: {exc}")

    # -- checks -----------------------------------------------------------
    async def run(self) -> int:
        await self.check(1, "whoami", self.check_whoami)
        await self.check(2, "asset by serial has company/model/category/status", self.check_asset)
        await self.check(3, "status labels include Ready to deploy and Maintenance", self.check_labels)
        await self.check(4, "update asset status and restore", self.check_update_status)
        await self.check(5, "search_users returns company", self.check_search_users)
        await self.check(6, "list_user_assets includes TEST-SN-0005", self.check_user_assets)
        await self.check(7, "checkin TEST-SN-0005 clears assignee", self.check_checkin)
        await self.check(8, "checkout TEST-SN-0001 to test.btech1", self.check_checkout)
        await self.check(9, "upload file and list it", self.check_upload)
        await self.check(10, "cleanup checkin and Ready to deploy", self.check_cleanup)
        await self.check(11, "error shapes (not found, bad token)", self.check_errors)
        self.write_report()
        passed = sum(1 for _, _, ok, _ in self.results if ok)
        print(f"\n{passed}/11 PASS")
        return 0 if passed == 11 else 1

    async def client(self) -> SnipeItClient:
        if not BASE_URL or not TOKEN:
            raise SystemExit("missing SNIPEIT_URL/SNIPEIT_TOKEN")
        return SnipeItClient(BASE_URL, ServiceAccountProvider(TOKEN))

    async def user_id(self, client: SnipeItClient, username: str) -> int:
        user = await client.find_user(username)
        if user is None:
            raise AssertionError(f"user {username} not found")
        return user.id

    async def ready_id(self, client: SnipeItClient) -> int:
        label_id = await client.find_status_label_id(READY)
        if label_id is None:
            raise AssertionError(f"status label {READY!r} not found")
        return label_id

    async def check_whoami(self) -> str:
        client = await self.client()
        try:
            me = await client.whoami()
        finally:
            await client.aclose()
        if not me.id:
            raise AssertionError("whoami returned no id")
        return f"user={me.username or me.name or me.id}"

    async def check_asset(self) -> str:
        client = await self.client()
        try:
            asset = await client.get_asset_by_serial("TEST-SN-0001")
        finally:
            await client.aclose()
        assert asset.company == "B.tech", f"company={asset.company!r}"
        assert asset.model, "model missing"
        assert asset.category, "category missing"
        assert asset.status, "status missing"
        assert asset.company_id is not None, "company_id missing"
        assert asset.status_id is not None, "status_id missing"
        return f"company={asset.company} model={asset.model} status={asset.status}"

    async def check_labels(self) -> str:
        client = await self.client()
        try:
            labels = await client.list_status_labels()
        finally:
            await client.aclose()
        names = {name.casefold() for _, name in labels}
        assert READY.casefold() in names, "Ready to deploy missing"
        assert MAINTENANCE.casefold() in names, "Maintenance missing"
        return ", ".join(name for _, name in labels[:6])

    async def check_update_status(self) -> str:
        client = await self.client()
        try:
            asset = await client.get_asset_by_serial("TEST-SN-0001")
            maintenance = await client.find_status_label_id(MAINTENANCE)
            ready = await self.ready_id(client)
            assert maintenance is not None, "Maintenance label missing"
            await client.update_asset_status(asset.id, maintenance)
            changed = await client.get_asset(asset.id)
            assert (changed.status or "").casefold() == MAINTENANCE.casefold(), (
                f"status after update={changed.status!r}"
            )
            await client.update_asset_status(asset.id, ready)
            restored = await client.get_asset(asset.id)
            assert (restored.status or "").casefold() == READY.casefold(), (
                f"status after restore={restored.status!r}"
            )
        finally:
            await client.aclose()
        return "Maintenance -> Ready to deploy"

    async def check_search_users(self) -> str:
        client = await self.client()
        try:
            users = await client.search_users("test.btech")
        finally:
            await client.aclose()
        assert users, "no users returned"
        without = [u.username for u in users if not u.company]
        assert not without, f"users without company: {without}"
        return f"{len(users)} users, all with company"

    async def check_user_assets(self) -> str:
        client = await self.client()
        try:
            user_id = await self.user_id(client, "test.btech2")
            assets = await client.list_user_assets(user_id)
        finally:
            await client.aclose()
        serials = {a.serial for a in assets}
        assert "TEST-SN-0005" in serials, f"serials={sorted(s for s in serials if s)}"
        return "TEST-SN-0005 present"

    async def check_checkin(self) -> str:
        client = await self.client()
        try:
            asset = await client.get_asset_by_serial("TEST-SN-0005")
            user_id = await self.user_id(client, "test.btech2")
            await client.checkin_asset(asset.id, note="Phase 01 probe checkin")
            cleared = await client.get_asset(asset.id)
            assert cleared.assigned_to_id is None, (
                f"assigned_to_id={cleared.assigned_to_id}"
            )
            await client.checkout_asset_to_user(
                asset.id, user_id, note="Phase 01 probe restore"
            )
            restored = await client.get_asset(asset.id)
            assert restored.assigned_to_id == user_id, (
                f"restore assigned_to_id={restored.assigned_to_id}"
            )
        finally:
            await client.aclose()
        return "assignee cleared and restored"

    async def check_checkout(self) -> str:
        client = await self.client()
        try:
            asset = await client.get_asset_by_serial("TEST-SN-0001")
            if asset.assigned_to_id is not None:
                await client.checkin_asset(asset.id, note="Phase 01 probe precondition")
            user_id = await self.user_id(client, "test.btech1")
            deployed_id = await client.find_status_label_id("Deployed")
            assert deployed_id is not None, "Deployed label missing"
            await client.checkout_asset_to_user(
                asset.id,
                user_id,
                note="Phase 01 probe checkout",
                status_id=deployed_id,
            )
            after = await client.get_asset(asset.id)
            assert after.assigned_to_id == user_id, (
                f"assigned_to_id={after.assigned_to_id}"
            )
            assert (after.status or "").casefold() == "deployed", (
                f"status={after.status!r}"
            )
        finally:
            await client.aclose()
        return f"assigned to test.btech1 (id {user_id}), status=Deployed"

    async def check_upload(self) -> str:
        client = await self.client()
        filename = f"probe-{os.getpid()}.png"
        try:
            asset = await client.get_asset_by_serial("TEST-SN-0001")
            await client.upload_asset_file(
                asset.id, filename, PNG_BYTES, "image/png", "Phase 01 probe upload"
            )
            files = await client.list_asset_files(asset.id)
        finally:
            await client.aclose()
        names = [f.filename for f in files]
        assert any(filename in name for name in names), f"files={names[:5]}"
        return f"{filename} listed ({len(files)} files)"

    async def check_cleanup(self) -> str:
        client = await self.client()
        try:
            asset = await client.get_asset_by_serial("TEST-SN-0001")
            await client.checkin_asset(asset.id, note="Phase 01 probe cleanup")
            ready = await self.ready_id(client)
            await client.update_asset_status(asset.id, ready)
            after = await client.get_asset(asset.id)
            assert after.assigned_to_id is None, f"still assigned to {after.assigned_to_id}"
            assert (after.status or "").casefold() == READY.casefold(), (
                f"status={after.status!r}"
            )
        finally:
            await client.aclose()
        return "checked in, Ready to deploy"

    async def check_errors(self) -> str:
        client = await self.client()
        try:
            try:
                await client.get_asset_by_serial("NOPE-999")
            except SnipeItNotFound:
                pass
            else:
                raise AssertionError("NOPE-999 did not raise SnipeItNotFound")
        finally:
            await client.aclose()

        bad = SnipeItClient(BASE_URL, ServiceAccountProvider("wrong-token"))
        try:
            try:
                await bad.whoami()
            except SnipeItAuthError:
                pass
            else:
                raise AssertionError("bad token did not raise SnipeItAuthError")
        finally:
            await bad.aclose()
        return "SnipeItNotFound + SnipeItAuthError"

    # -- report -----------------------------------------------------------
    def write_report(self) -> None:
        rows = "\n".join(
            f"| {number} | {name} | {'PASS' if ok else 'FAIL'} | {detail} |"
            for number, name, ok, detail in self.results
        )
        content = (
            "# Snipe-IT integration report\n\n"
            "Live instance: `deploy/snipeit-dev` (Snipe-IT v8), local only.\n"
            "Probe: `python tools/snipeit_probe.py` (uses `app/clients/snipeit.py`).\n"
            "No tokens or secrets are recorded here.\n\n"
            "## Phase 01\n\n"
            "| # | Check | Result | Detail |\n|---|---|---|---|\n"
            f"{rows}\n"
        )
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(content, encoding="utf-8")
        print(f"report -> {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(asyncio.run(Probe().run()))
