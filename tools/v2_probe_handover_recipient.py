"""Phase 03 probe: recipient flow against the REAL Snipe-IT dev stack.

    python tools/v2_probe_handover_recipient.py

Uses the app services and client, prints PASS/FAIL per check, and appends the
result to ``docs/snipeit-integration-report.md`` under "Round 2".
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
from app.db.engine import get_sessionmaker  # noqa: E402
from app.domain.handover_rules import case_warnings  # noqa: E402
from app.services.handovers import HandoverService  # noqa: E402
from app.services.snipeit_ops import SnipeItHandoverService  # noqa: E402

SERIAL = "TEST-SN-0001"
ENGINEER = "probe.engineer@example.test"
REPORT = ROOT / "docs" / "snipeit-integration-report.md"


class Probe:
    def __init__(self) -> None:
        self.results: list[tuple[int, str, bool, str]] = []

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
        handover_id = None
        try:
            async with factory() as session:
                service = HandoverService(session)
                existing = await service.find_active_by_serial(SERIAL)
                if existing is not None:
                    await service.cancel(existing.id, actor=ENGINEER)
                    await session.commit()
                handover = await service.create(
                    device_serial=SERIAL,
                    engineer_email=ENGINEER,
                    engineer_name="Probe Engineer",
                    client=client,
                )
                await session.commit()
                handover_id = handover.id

            async with factory() as session:
                service = HandoverService(session)
                users = await service.search_snipeit_users(
                    handover_id, "test.", client=client
                )
                by_username = {user["username"]: user for user in users}
                mylo = by_username.get("test.mylo1")
                btech = by_username.get("test.btech2")
                ok = (
                    mylo is not None
                    and mylo["same_company"] is False
                    and btech is not None
                    and btech["same_company"] is True
                )
                self.record(
                    1,
                    "user search marks Mylo false and B.tech true",
                    ok,
                    f"mylo={mylo} btech={btech}",
                )

            async with factory() as session:
                service = SnipeItHandoverService(session)
                view = await service.choose_recipient(
                    handover_id,
                    mode="snipeit",
                    user_id=mylo["id"],
                    actor=ENGINEER,
                    client=client,
                )
                await session.commit()
                stage = next(
                    item for item in view.stages if item.stage == "recipient_check"
                )
                warnings = [
                    warning.code
                    for warning in case_warnings(
                        view.handover.device_company,
                        view.handover.recipient_company,
                    )
                ]
                events = [event.type for event in view.events]
                self.record(
                    2,
                    "Mylo recipient is accepted with a company warning",
                    stage.status == "passed"
                    and "company_mismatch" in warnings
                    and "company_mismatch_warning" in events,
                    f"status={stage.status!r} warnings={warnings} "
                    f"events={events}",
                )

            # Round 2: the company warning must not block the checkout.
            async with factory() as session:
                service = SnipeItHandoverService(session)
                view = await service.checkout(
                    handover_id, actor=ENGINEER, client=client
                )
                await session.commit()
                stage = next(
                    item for item in view.stages if item.stage == "checkout"
                )
                asset = await client.get_asset_by_serial(SERIAL)
                self.record(
                    3,
                    "device is checked out to the Mylo user with a warning",
                    stage.status == "passed" and asset.assigned_to_id == mylo["id"],
                    f"stage={stage.status!r} assignee={asset.assigned_to_id!r} "
                    f"expected={mylo['id']!r}",
                )

            # Release the device and start a second case for the B.tech flow.
            async with factory() as session:
                service = HandoverService(session)
                await service.cancel(handover_id, actor=ENGINEER)
                await session.commit()
            asset = await client.get_asset_by_serial(SERIAL)
            if asset.assigned_to_id is not None:
                await client.checkin_asset(asset.id, "Round 2 probe setup")
            async with factory() as session:
                service = HandoverService(session)
                handover = await service.create(
                    device_serial=SERIAL,
                    engineer_email=ENGINEER,
                    engineer_name="Probe Engineer",
                    client=client,
                )
                await session.commit()
                handover_id = handover.id

            async with factory() as session:
                service = SnipeItHandoverService(session)
                view = await service.choose_recipient(
                    handover_id,
                    mode="snipeit",
                    user_id=btech["id"],
                    actor=ENGINEER,
                    client=client,
                )
                await session.commit()
                stage = next(
                    item for item in view.stages if item.stage == "recipient_check"
                )
                self.record(
                    4,
                    "B.tech recipient is accepted",
                    stage.status == "passed",
                    f"status={stage.status!r}",
                )

            async with factory() as session:
                service = SnipeItHandoverService(session)
                items = await service.list_recipient_items(
                    handover_id, client=client
                )
                item = next(
                    (entry for entry in items if entry["serial"] == "TEST-SN-0005"),
                    None,
                )
                if item is None:
                    other = await client.get_asset_by_serial("TEST-SN-0005")
                    if other.assigned_to_id is not None:
                        await client.checkin_asset(
                            other.id, "Round 2 probe setup"
                        )
                    labels = await client.list_status_labels()
                    deployed_id = next(
                        (
                            label_id
                            for label_id, name in labels
                            if name.strip().casefold() == "deployed"
                        ),
                        None,
                    )
                    await client.checkout_asset_to_user(
                        other.id,
                        btech["id"],
                        "Round 2 probe setup",
                        status_id=deployed_id,
                    )
                    items = await service.list_recipient_items(
                        handover_id, client=client
                    )
                    item = next(
                        (
                            entry
                            for entry in items
                            if entry["serial"] == "TEST-SN-0005"
                        ),
                        None,
                    )
                self.record(
                    5,
                    "recipient items include TEST-SN-0005",
                    item is not None,
                    f"items={items}",
                )

            async with factory() as session:
                service = SnipeItHandoverService(session)
                outcomes = await service.checkin_recipient_items(
                    handover_id,
                    [item["asset_id"]],
                    actor=ENGINEER,
                    client=client,
                )
                await session.commit()
                asset = await client.get_asset(item["asset_id"])
                self.record(
                    6,
                    "TEST-SN-0005 is checked in",
                    outcomes[0].status == "checked_in"
                    and asset.assigned_to_id is None,
                    f"outcome={outcomes[0].status!r} assignee={asset.assigned_to_id!r}",
                )

            async with factory() as session:
                service = SnipeItHandoverService(session)
                view = await service.confirm_recipient_items(
                    handover_id, actor=ENGINEER, client=client
                )
                await session.commit()
                stage = next(
                    item for item in view.stages if item.stage == "recipient_items"
                )
                self.record(
                    7,
                    "recipient items are confirmed",
                    stage.status == "passed",
                    f"status={stage.status!r} detail={stage.detail!r}",
                )

            async with factory() as session:
                service = SnipeItHandoverService(session)
                view = await service.checkout(
                    handover_id, actor=ENGINEER, client=client
                )
                await session.commit()
                stage = next(
                    item for item in view.stages if item.stage == "checkout"
                )
                asset = await client.get_asset_by_serial(SERIAL)
                self.record(
                    8,
                    "device is checked out with Deployed status",
                    stage.status == "passed"
                    and asset.assigned_to_id == btech["id"]
                    and (asset.status or "").casefold() == "deployed",
                    f"stage={stage.status!r} assignee={asset.assigned_to_id!r} "
                    f"status={asset.status!r}",
                )

            async with factory() as session:
                service = HandoverService(session)
                await service.cancel(handover_id, actor=ENGINEER)
                await session.commit()
            self.record(9, "case cancelled (cleanup)", True)
        except Exception as exc:  # noqa: BLE001 - report the real error
            self.record(
                99,
                "probe error",
                False,
                f"{type(exc).__name__}: {exc}",
            )
        finally:
            await self.cleanup(client, factory, handover_id)
            await client.aclose()

        self.write_report()
        passed = sum(1 for _, _, ok, _ in self.results if ok)
        print(f"\n{passed}/{len(self.results)} PASS")
        return 0 if passed == len(self.results) else 1

    async def cleanup(self, client, factory, handover_id) -> None:
        try:
            asset = await client.get_asset_by_serial(SERIAL)
            if asset.assigned_to_id is not None:
                await client.checkin_asset(asset.id, "Phase 03 probe cleanup")
            ready_id = await client.find_status_label_id("Ready to deploy")
            if ready_id is not None:
                await client.update_asset_status(asset.id, ready_id)
            if handover_id is not None:
                async with factory() as session:
                    service = HandoverService(session)
                    await service.cancel(handover_id, actor=ENGINEER)
                    await session.commit()
        except Exception as exc:  # noqa: BLE001 - cleanup must not hide the result
            print(f"cleanup warning: {type(exc).__name__}: {exc}")

    def write_report(self) -> None:
        rows = "\n".join(
            f"| {number} | {name} | {'PASS' if ok else 'FAIL'} | {detail} |"
            for number, name, ok, detail in self.results
        )
        section = (
            "\n## Round 2\n\n"
            "| # | Check | Result | Detail |\n|---|---|---|---|\n"
            f"{rows}\n"
        )
        existing = REPORT.read_text(encoding="utf-8") if REPORT.exists() else ""
        marker = "\n## Round 2\n"
        if marker in existing:
            existing = existing[: existing.index(marker)]
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(existing.rstrip() + "\n" + section, encoding="utf-8")
        print(f"report -> {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(asyncio.run(Probe().run()))
