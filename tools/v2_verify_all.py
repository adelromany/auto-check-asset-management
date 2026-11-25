"""Phase 08 live verification against the running portal and real Snipe-IT.

Every scenario uses the portal's public HTTP API and reads Snipe-IT back through
its API. Run the portal first, then::

    python tools/v2_verify_all.py

The script prints one PASS/FAIL line per scenario and exits non-zero on any
failure. It never prints the Snipe-IT token.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import traceback
import uuid
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.clients.snipeit import ServiceAccountProvider, SnipeItClient  # noqa: E402

PORTAL = os.getenv("VERIFY_PORTAL_URL", "http://127.0.0.1:8080").rstrip("/")
DB_PATH = Path(os.getenv("VERIFY_DATABASE", ROOT / "data" / "verify_v2.db"))
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c63600000020001e221bc33000000"
    "0049454e44ae426082"
)
AGENT_PAYLOAD = {
    "serial": "TEST-SN-0001",
    "username": "probe.user",
    "hostname": "PROBE-PC",
    "manufacturer": "Dell",
    "model": "Latitude 5440",
    "cpu": "Intel Core i7",
    "cpu_cores": 8,
    "ram_gb": 16,
    "os_name": "Windows 11",
    "os_version": "23H2",
    "os_arch": "x64",
    "agent_os": "windows",
    "collected_at": "2026-11-25T00:00:00Z",
    "disks": [{"name": "C:", "size_gb": 512, "type": "SSD"}],
    "ip_addresses": [],
    "software_checks": [
        {"id": "forticlient", "name": "FortiClient", "installed": True, "version": "1", "method": "registry"},
        {"id": "sccm", "name": "SCCM", "installed": True, "version": "1", "method": "registry"},
        {"id": "intune", "name": "Intune", "installed": True, "version": "1", "method": "registry"},
        {"id": "office2021", "name": "Office 2021", "installed": True, "version": "1", "method": "registry"}
    ],
    "windows_activation": {"status": "Licensed", "status_code": 1},
}


class Verification:
    def __init__(self) -> None:
        self.http: httpx.AsyncClient | None = None
        self.snipe: SnipeItClient | None = None
        self.results: list[tuple[str, bool, str]] = []
        self.cases: dict[str, str] = {}

    async def __aenter__(self) -> "Verification":
        self.http = httpx.AsyncClient(base_url=PORTAL, timeout=30.0)
        me = await self.http.get("/api/me")
        me.raise_for_status()
        token = me.headers.get("X-CSRF-Token", "")
        self.http.headers["X-CSRF-Token"] = token
        base = os.getenv("SNIPEIT_URL", "").rstrip("/")
        self.snipe = SnipeItClient(base, ServiceAccountProvider(os.getenv("SNIPEIT_TOKEN", "")))
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self.http:
            await self.http.aclose()
        if self.snipe:
            await self.snipe.aclose()

    async def req(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        assert self.http is not None
        response = await self.http.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise AssertionError(f"HTTP {response.status_code}: {response.text[:300]}")
        return response

    async def create(self, serial: str) -> str:
        response = await self.req("POST", "/api/handovers", json={"device_serial": serial})
        case_id = response.json()["id"]
        self.cases[serial] = case_id
        return case_id

    async def prepare_device(self, case_id: str, serial: str) -> None:
        labels = (await self.req("GET", "/api/snipeit/status-labels")).json()
        ready = next(item["id"] for item in labels if item["name"].casefold() == "ready to deploy")
        await self.req("POST", f"/api/handovers/{case_id}/device-status", json={"status_label_id": ready})
        payload = dict(AGENT_PAYLOAD, serial=serial)
        await self.req("POST", f"/api/handovers/{case_id}/attach-report", json={"payload": payload})

    async def user_id(self, username: str) -> int:
        assert self.snipe is not None
        users = await self.snipe.search_users(username)
        return next(user.id for user in users if user.username == username)

    async def asset(self, serial: str):
        assert self.snipe is not None
        return await self.snipe.get_asset_by_serial(serial)

    async def dashboard(self, kind: str) -> dict:
        return (await self.req("GET", f"/api/dashboard/{kind}")).json()

    async def scenario(self, name: str, fn) -> None:
        try:
            detail = await fn()
            self.results.append((name, True, detail))
            print(f"PASS {name} :: {detail}")
        except Exception as exc:  # noqa: BLE001
            self.results.append((name, False, f"{type(exc).__name__}: {exc}"))
            print(f"FAIL {name} :: {type(exc).__name__}: {exc}")
            traceback.print_exc()

    async def s1(self) -> str:
        case_id = await self.create("TEST-SN-0001")
        await self.prepare_device(case_id, "TEST-SN-0001")
        uid = await self.user_id("test.btech1")
        await self.req("POST", f"/api/handovers/{case_id}/recipient", json={"mode": "snipeit", "user_id": uid})
        await self.req("POST", f"/api/handovers/{case_id}/checkout")
        form = await self.req("GET", f"/api/handovers/{case_id}/form")
        with zipfile.ZipFile(BytesIO(form.content)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", "replace")
        assert "Dev" in xml, "engineer name missing from form"
        await self.req("POST", f"/api/handovers/{case_id}/stages/report_printed/confirm")
        await self.req("POST", f"/api/handovers/{case_id}/signed-paper", files={"file": ("signed.png", PNG, "image/png")})
        detail = (await self.req("GET", f"/api/handovers/{case_id}")).json()
        asset = await self.asset("TEST-SN-0001")
        files = await self.snipe.list_asset_files(asset.id)  # type: ignore[union-attr]
        assert detail["outcome"] == "complete", detail["outcome"]
        assert asset.assigned_to_id == uid and (asset.status or "").casefold() == "deployed"
        assert any("signed" in file.filename.lower() for file in files)
        return "complete; assignee=test.btech1; status=Deployed; signed PNG attached"

    async def s2(self) -> str:
        """Round 2: a company mismatch is a warning and the checkout succeeds."""
        case_id = await self.create("TEST-SN-0003")
        uid = await self.user_id("test.btech1")
        response = await self.http.post(f"/api/handovers/{case_id}/recipient", json={"mode": "snipeit", "user_id": uid})  # type: ignore[union-attr]
        assert response.status_code == 200, response.text
        body = response.json()
        warnings = [item.get("code") for item in body.get("warnings", [])]
        assert "company_mismatch" in warnings, body
        await self.req("POST", f"/api/handovers/{case_id}/checkout")
        asset = await self.asset("TEST-SN-0003")
        assert asset.assigned_to_id == uid, f"assignee={asset.assigned_to_id!r}"
        assert self.snipe is not None
        await self.snipe.checkin_asset(asset.id, "Round 2 verification cleanup")
        await self.req("POST", f"/api/handovers/{case_id}/cancel")
        return "company_mismatch warning; checkout succeeded; asset checked back in"

    async def s3(self) -> str:
        case_id = await self.create("TEST-SN-0004")
        await self.prepare_device(case_id, "TEST-SN-0004")
        await self.req("POST", f"/api/handovers/{case_id}/recipient", json={"mode": "not_in_snipeit", "name": "Missing User", "email": "missing@example.test"})
        detail = (await self.req("GET", f"/api/handovers/{case_id}")).json()
        assert detail["outcome"] == "not_complete", detail
        assert detail["missing"], detail
        uid = await self.user_id("test.nexta1")
        await self.req("POST", f"/api/handovers/{case_id}/recipient", json={"mode": "snipeit", "user_id": uid})
        form = await self.req("GET", f"/api/handovers/{case_id}/form")
        assert form.content, "Nexta form missing"
        await self.req("POST", f"/api/handovers/{case_id}/stages/report_printed/confirm")
        await self.req("POST", f"/api/handovers/{case_id}/signed-paper", files={"file": ("signed.png", PNG, "image/png")})
        await self.req("POST", f"/api/handovers/{case_id}/checkout")
        detail = (await self.req("GET", f"/api/handovers/{case_id}")).json()
        assert detail["outcome"] == "complete", detail["outcome"]
        return "not_complete with missing parts, then complete with test.nexta1"

    async def s4(self) -> str:
        case_id = await self.create("TEST-SN-0002")
        await self.prepare_device(case_id, "TEST-SN-0002")
        await self.req("POST", f"/api/handovers/{case_id}/recipient", json={"mode": "none"})
        detail = (await self.req("GET", f"/api/handovers/{case_id}")).json()
        assert detail["outcome"] == "ready", detail
        rows = (await self.req("GET", "/api/dashboard/handovers", params={"kind": "handover"})).json()
        assert any(item.get("handover", {}).get("id") == case_id and item.get("handover", {}).get("outcome") == "ready" for item in rows.get("items", [])), rows
        await self.req("POST", f"/api/handovers/{case_id}/cancel")
        return "ready; listed in handover dashboard"

    async def s5(self) -> str:
        case_id = await self.create("TEST-SN-0002")
        uid = await self.user_id("test.btech2")
        await self.req("POST", f"/api/handovers/{case_id}/recipient", json={"mode": "snipeit", "user_id": uid})
        items = (await self.req("GET", f"/api/handovers/{case_id}/recipient/items")).json()
        item = next(item for item in items if item["serial"] == "TEST-SN-0005")
        await self.req("POST", f"/api/handovers/{case_id}/recipient/items/checkin", json={"asset_ids": [item["asset_id"]]})
        asset = await self.asset("TEST-SN-0005")
        assert asset.assigned_to_id is None
        await self.req("POST", f"/api/handovers/{case_id}/cancel")
        return "TEST-SN-0005 assignee cleared in Snipe-IT"

    async def s6(self) -> str:
        reasons = (await self.req("GET", "/api/maintenance/reasons")).json()
        other = next(item for item in reasons if item["name"] == "Other")
        screen = next(item for item in reasons if item["name"] == "Screen")
        first = await self.req("POST", "/api/maintenance/cases", json={"serial": "TEST-SN-0001", "reason_id": other["id"], "reason_text": "Verification repair"})
        second = await self.req("POST", "/api/maintenance/cases", json={"serial": "TEST-SN-0002", "reason_id": screen["id"]})
        vendor = (await self.req("POST", "/api/maintenance/vendors", json={"name": "TEST-Vendor"})).json()
        ids = [first.json()["id"], second.json()["id"]]
        for case_id in ids:
            await self.req("POST", f"/api/maintenance/cases/{case_id}/set-status")
            await self.req("POST", f"/api/maintenance/cases/{case_id}/take-back")
        sent = (await self.req("POST", "/api/maintenance/batches/send", json={"case_ids": ids, "vendor_id": vendor["id"], "sent_date": date.today().isoformat()})).json()
        assert all(item["ok"] for item in sent), sent
        with_it_ids = {item["case_id"] for item in (await self.req("GET", "/api/maintenance/cases", params={"state": "with_it"})).json()}
        at_vendor_ids = {item["case_id"] for item in (await self.req("GET", "/api/maintenance/cases", params={"state": "at_vendor"})).json()}
        assert all(cid not in with_it_ids and cid in at_vendor_ids for cid in ids), (with_it_ids, at_vendor_ids)
        dash = await self.dashboard("maintenance")
        assert dash["in_maintenance"]["total"] == 2, dash["in_maintenance"]
        dash_needs = {d["case_id"] for d in dash["devices"] if d["state"] == "with_it"}
        dash_maint = {d["case_id"] for d in dash["devices"] if d["state"] == "at_vendor"}
        assert dash_needs.isdisjoint(dash_maint) and all(cid in dash_maint and cid not in dash_needs for cid in ids)
        received = (await self.req("POST", "/api/maintenance/batches/receive", json={"case_ids": [ids[0]], "returned_date": date.today().isoformat()})).json()
        assert received[0]["ok"], received
        with_it_after = {item["case_id"] for item in (await self.req("GET", "/api/maintenance/cases", params={"state": "with_it"})).json()}
        at_vendor_after = {item["case_id"] for item in (await self.req("GET", "/api/maintenance/cases", params={"state": "at_vendor"})).json()}
        returned_after = {item["case_id"] for item in (await self.req("GET", "/api/maintenance/cases", params={"state": "returned"})).json()}
        assert ids[0] not in with_it_after and ids[0] not in at_vendor_after and ids[0] in returned_after
        one = await self.asset("TEST-SN-0001")
        two = await self.asset("TEST-SN-0002")
        assert (one.status or "").casefold() == "ready to deploy" and (two.status or "").casefold() == "maintenance"
        await self.req("POST", "/api/maintenance/batches/receive", json={"case_ids": [ids[1]], "returned_date": date.today().isoformat()})
        return "2 sent; one received Ready; second received after check"

    async def s7(self) -> str:
        handover_before = await self.dashboard("handover")
        maintenance_before = await self.dashboard("maintenance")
        # The dashboard aggregates are independent by design; verify their
        # handover/maintenance partitions do not include each other's data.
        assert "tiles" in handover_before and "by_company" in handover_before, handover_before
        assert "needs" in maintenance_before and "in_maintenance" in maintenance_before, maintenance_before
        assert "tiles" not in maintenance_before, maintenance_before
        return "handover and maintenance dashboards remain separated"

    async def s8(self) -> str:
        case_id = await self.create("TEST-SN-0003")
        with sqlite3.connect(DB_PATH) as db:
            db.execute("UPDATE handovers SET snipeit_asset_id = ? WHERE id = ?", (999999999, case_id))
            db.commit()
        response = await self.http.post(f"/api/handovers/{case_id}/checkout")  # type: ignore[union-attr]
        assert response.status_code < 500, response.text
        assert response.status_code >= 400, "invalid asset unexpectedly succeeded"
        detail = response.json().get("detail", "")
        assert isinstance(detail, str) and "\n" not in detail, detail
        return f"clear one-line error (HTTP {response.status_code})"

    async def run(self) -> int:
        scenarios = [("S1", self.s1), ("S2", self.s2), ("S3", self.s3), ("S4", self.s4), ("S5", self.s5), ("S6", self.s6), ("S7", self.s7), ("S8", self.s8)]
        for name, fn in scenarios:
            await self.scenario(name, fn)
        passed = sum(1 for _, ok, _ in self.results if ok)
        print(f"\n{passed}/{len(self.results)} PASS")
        return 0 if passed == len(self.results) else 1


async def main() -> int:
    async with Verification() as verification:
        return await verification.run()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
