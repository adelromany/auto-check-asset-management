"""Phase 02 probe: the V2 handover device flow against the REAL dev stack.

Uses the app's own services (``HandoverService`` / ``SnipeItHandoverService``)
against the local portal database and the real Snipe-IT dev instance.

    python tools/v2_probe_handover_device.py

Prints PASS/FAIL per check and appends the result to
``docs/snipeit-integration-report.md`` under "Phase 02".
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
                handover = await service.create(
                    device_serial=SERIAL,
                    engineer_email=ENGINEER,
                    engineer_name="Probe Engineer",
                    client=client,
                )
                await session.commit()
                handover_id = handover.id

            self.record(
                1,
                "case created from the real device",
                True,
            )

            async with factory() as session:
                service = HandoverService(session)
                handover = await service.get(handover_id)
                await session.refresh(handover)
                company = handover.device_company
                model = handover.device_model
                category = handover.device_category
            ok = company == "B.tech" and bool(model) and bool(category)
            self.record(
                2,
                "case stores company, model and category",
                ok,
                f"company={company!r} model={model!r} category={category!r}",
            )

            labels = await client.list_status_labels()
            maintenance_id = next(
                (label_id for label_id, name in labels if name.casefold() == "maintenance"),
                None,
            )
            ready_id = next(
                (
                    label_id
                    for label_id, name in labels
                    if name.casefold() == "ready to deploy"
                ),
                None,
            )
            self.record(
                3,
                "status labels found (Maintenance, Ready to deploy)",
                maintenance_id is not None and ready_id is not None,
                f"maintenance={maintenance_id} ready={ready_id}",
            )

            async with factory() as session:
                service = SnipeItHandoverService(session)
                view = await service.set_device_status(
                    handover_id,
                    status_label_id=maintenance_id,
                    actor=ENGINEER,
                    client=client,
                )
                await session.commit()
                stage = next(
                    item for item in view.stages if item.stage == "device_status"
                )
            ok = stage.status == "failed" and stage.reason == "Status is Maintenance"
            self.record(
                4,
                "Maintenance label fails the device-status part",
                ok,
                f"status={stage.status!r} reason={stage.reason!r}",
            )

            async with factory() as session:
                service = SnipeItHandoverService(session)
                view = await service.set_device_status(
                    handover_id,
                    status_label_id=ready_id,
                    actor=ENGINEER,
                    client=client,
                )
                await session.commit()
                stage = next(
                    item for item in view.stages if item.stage == "device_status"
                )
            self.record(
                5,
                "Ready to deploy passes the device-status part",
                stage.status == "passed",
                f"status={stage.status!r} reason={stage.reason!r}",
            )

            async with factory() as session:
                service = HandoverService(session)
                await service.cancel(handover_id, actor=ENGINEER)
                await session.commit()
            self.record(6, "case cancelled (cleanup)", True)
        except Exception as exc:  # noqa: BLE001 - report the real error
            self.record(
                99,
                "probe error",
                False,
                f"{type(exc).__name__}: {exc}",
            )
        finally:
            await client.aclose()

        self.write_report()
        passed = sum(1 for _, _, ok, _ in self.results if ok)
        print(f"\n{passed}/{len(self.results)} PASS")
        return 0 if passed == len(self.results) else 1

    def write_report(self) -> None:
        rows = "\n".join(
            f"| {number} | {name} | {'PASS' if ok else 'FAIL'} | {detail} |"
            for number, name, ok, detail in self.results
        )
        section = (
            "\n## Phase 02\n\n"
            "| # | Check | Result | Detail |\n|---|---|---|---|\n"
            f"{rows}\n"
        )
        existing = REPORT.read_text(encoding="utf-8") if REPORT.exists() else ""
        marker = "\n## Phase 02\n"
        if marker in existing:
            existing = existing[: existing.index(marker)]
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(existing.rstrip() + "\n" + section, encoding="utf-8")
        print(f"report -> {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(asyncio.run(Probe().run()))
