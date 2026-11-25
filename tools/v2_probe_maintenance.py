"""Phase 06 probe: maintenance backend against REAL Snipe-IT.

    python tools/v2_probe_maintenance.py

Uses only TEST-SN-0004, TEST-SN-0005 and TEST-Vendor. It exercises the app's
maintenance service/client and appends the result to the integration report.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import delete

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.clients.snipeit import ServiceAccountProvider, SnipeItClient  # noqa: E402
from app.db.engine import get_sessionmaker  # noqa: E402
from app.db.models.maintenance import MaintenanceDestination  # noqa: E402
from app.repositories.maintenance import MaintenanceRepository  # noqa: E402
from app.services.dashboard import DashboardService  # noqa: E402
from app.services.handovers import HandoverService  # noqa: E402
from app.services.maintenance import MaintenanceService  # noqa: E402

SERIALS = ("TEST-SN-0004", "TEST-SN-0005")
VENDOR_NAME = "TEST-Vendor"
ENGINEER = "probe.engineer@example.test"
REPORT = ROOT / "docs" / "snipeit-integration-report.md"


class Probe:
    def __init__(self) -> None:
        self.results: list[tuple[int, str, bool, str]] = []
        self.case_ids: list[object] = []

    def record(self, number: int, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((number, name, ok, detail))
        print(
            f"{'PASS' if ok else 'FAIL'} {number:02d} {name}"
            + (f" :: {detail}" if detail and not ok else "")
        )

    async def run(self) -> int:
        factory = get_sessionmaker()
        client = SnipeItClient(
            os.getenv("SNIPEIT_URL", "").rstrip("/"),
            ServiceAccountProvider(os.getenv("SNIPEIT_TOKEN", "")),
        )
        try:
            await self.cleanup_cases(factory)
            await self.ensure_asset_ready(client)

            async with factory() as session:
                service = MaintenanceService(session)
                device = await service.lookup_device(SERIALS[0], client=client)
                reason = next(
                    item
                    for item in await MaintenanceRepository(session).list_diagnosis_categories()
                    if item.name == "Screen"
                )
                case = await service.create_case(
                    serial=SERIALS[0],
                    reason_id=reason.id,
                    reason_text=None,
                    planned_vendor_id=None,
                    engineer_email=ENGINEER,
                    engineer_name="Probe Engineer",
                    client=client,
                )
                await session.commit()
                self.case_ids.append(case.handover.id)
                self.record(
                    1,
                    "lookup and create store the Nexta device snapshot",
                    device.company == "Nexta" and case.handover.device_company == "Nexta",
                    f"lookup_company={device.company!r} stored={case.handover.device_company!r}",
                )

            async with factory() as session:
                view = await MaintenanceService(session).set_status(
                    self.case_ids[0], engineer_email=ENGINEER, client=client
                )
                await session.commit()
                operation = next(item for item in view.stages if item.stage == "snipeit_status")
            asset = await client.get_asset_by_serial(SERIALS[0])
            self.record(
                2,
                "set-status shows Maintenance in Snipe-IT",
                operation.status == "passed" and asset.status == "Maintenance",
                f"operation={operation.status!r} asset_status={asset.status!r}",
            )

            await self.ensure_assigned(client)
            async with factory() as session:
                service = MaintenanceService(session)
                reason = next(
                    item
                    for item in await MaintenanceRepository(session).list_diagnosis_categories()
                    if item.name == "Screen"
                )
                case = await service.create_case(
                    serial=SERIALS[1],
                    reason_id=reason.id,
                    reason_text=None,
                    planned_vendor_id=None,
                    engineer_email=ENGINEER,
                    engineer_name="Probe Engineer",
                    client=client,
                )
                await session.commit()
                self.case_ids.append(case.handover.id)
                taken = await service.take_back(
                    case.handover.id, engineer_email=ENGINEER, client=client
                )
                await session.commit()
                operation = next(item for item in taken.stages if item.stage == "taken_back")
                status_view = await service.set_status(
                    case.handover.id, engineer_email=ENGINEER, client=client
                )
                await session.commit()
            asset = await client.get_asset_by_serial(SERIALS[1])
            status_operation = next(
                item for item in status_view.stages if item.stage == "snipeit_status"
            )
            self.record(
                3,
                "take-back clears the user and set-status shows Maintenance",
                operation.status == "passed"
                and asset.assigned_to_id is None
                and status_operation.status == "passed"
                and asset.status == "Maintenance",
                f"take_back={operation.status!r} assignee={asset.assigned_to_id} status={asset.status!r}",
            )

            async with factory() as session:
                vendor = await MaintenanceRepository(session).ensure_vendor(VENDOR_NAME)
                await session.flush()
                vendor_id = vendor.id
                await session.commit()
            async with factory() as session:
                results = await MaintenanceService(session).batch_send(
                    [self.case_ids[0], self.case_ids[1]],
                    vendor_id=vendor_id,
                    sent_date=date.today(),
                    engineer_email=ENGINEER,
                )
                await session.commit()
            async with factory() as session:
                dashboard = await DashboardService(session).maintenance()
                await session.commit()
            vendor_group = next(
                item for item in dashboard.in_maintenance.by_vendor if item.name == VENDOR_NAME
            )
            self.record(
                4,
                "batch send puts both devices at the test vendor",
                all(item.ok for item in results)
                and dashboard.in_maintenance.total == 2
                and vendor_group.count == 2,
                f"results={[(item.case_id, item.ok) for item in results]} total={dashboard.in_maintenance.total} vendor={vendor_group.count}",
            )

            async with factory() as session:
                results = await MaintenanceService(session).batch_receive(
                    [self.case_ids[0]],
                    returned_date=date.today(),
                    engineer_email=ENGINEER,
                    client=client,
                )
                await session.commit()
            first = await client.get_asset_by_serial(SERIALS[0])
            second = await client.get_asset_by_serial(SERIALS[1])
            self.record(
                5,
                "receiving one device sets only that device Ready to deploy",
                results[0].ok
                and str(first.status).casefold() == "ready to deploy"
                and str(second.status).casefold() == "maintenance",
                f"first={first.status!r} second={second.status!r}",
            )

            async with factory() as session:
                results = await MaintenanceService(session).batch_receive(
                    [self.case_ids[1]],
                    returned_date=date.today(),
                    engineer_email=ENGINEER,
                    client=client,
                )
                await session.commit()
            first = await client.get_asset_by_serial(SERIALS[0])
            second = await client.get_asset_by_serial(SERIALS[1])
            self.record(
                6,
                "receiving the second device leaves both Ready to deploy",
                results[0].ok
                and str(first.status).casefold() == "ready to deploy"
                and str(second.status).casefold() == "ready to deploy",
                f"first={first.status!r} second={second.status!r}",
            )
        except Exception as exc:  # noqa: BLE001
            self.record(99, "probe error", False, f"{type(exc).__name__}: {exc}")
        finally:
            await self.cleanup_cases(factory)
            await self.cleanup_vendor(factory)
            await self.ensure_asset_ready(client)
            await client.aclose()

        self.write_report()
        passed = sum(1 for _, _, ok, _ in self.results if ok)
        print(f"\n{passed}/{len(self.results)} PASS")
        return 0 if passed == len(self.results) else 1

    async def ensure_assigned(self, client: SnipeItClient) -> None:
        asset = await client.get_asset_by_serial(SERIALS[1])
        if asset.assigned_to_id is not None:
            return
        users = await client.search_users("test.btech2")
        user = next(item for item in users if item.username == "test.btech2")
        deployed = await client.find_status_label_id("Deployed")
        await client.checkout_asset_to_user(
            asset.id, user.id, "Phase 06 probe assignment", status_id=deployed
        )

    async def ensure_asset_ready(self, client: SnipeItClient) -> None:
        ready = await client.find_status_label_id("Ready to deploy")
        if ready is None:
            return
        for serial in SERIALS:
            try:
                asset = await client.get_asset_by_serial(serial)
                if asset.assigned_to_id is not None:
                    await client.checkin_asset(asset.id, "Phase 06 probe cleanup")
                await client.update_asset_status(asset.id, ready)
            except Exception as exc:  # noqa: BLE001
                print(f"cleanup warning: {type(exc).__name__}: {exc}")

    async def cleanup_cases(self, factory) -> None:
        async with factory() as session:
            service = HandoverService(session)
            for serial in SERIALS:
                existing = await service.find_active_by_serial(serial)
                if existing is not None:
                    await service.cancel(existing.id, actor=ENGINEER)
            await session.commit()

    async def cleanup_vendor(self, factory) -> None:
        async with factory() as session:
            await session.execute(
                delete(MaintenanceDestination).where(
                    MaintenanceDestination.name_key == VENDOR_NAME.casefold()
                )
            )
            await session.commit()

    def write_report(self) -> None:
        rows = "\n".join(
            f"| {number} | {name} | {'PASS' if ok else 'FAIL'} | {detail} |"
            for number, name, ok, detail in self.results
        )
        section = (
            "\n## Phase 06\n\n"
            "| # | Check | Result | Detail |\n|---|---|---|---|\n"
            f"{rows}\n"
        )
        existing = REPORT.read_text(encoding="utf-8") if REPORT.exists() else ""
        marker = "\n## Phase 06\n"
        if marker in existing:
            existing = existing[: existing.index(marker)]
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(existing.rstrip() + "\n" + section, encoding="utf-8")
        print(f"report -> {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(asyncio.run(Probe().run()))
