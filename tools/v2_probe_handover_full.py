"""Phase 04 probe: the complete handover backend against REAL Snipe-IT.

    python tools/v2_probe_handover_full.py

Uses only TEST- assets, temporary forms/documents, and the app services/client.
It appends PASS/FAIL results to docs/snipeit-integration-report.md.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.clients.snipeit import ServiceAccountProvider, SnipeItClient  # noqa: E402
from app.db.engine import get_sessionmaker  # noqa: E402
from app.domain.handover_rules import case_outcome  # noqa: E402
from app.services.documents import DocumentService  # noqa: E402
from app.services.forms import FormService  # noqa: E402
from app.services.handovers import HandoverService, stage_states  # noqa: E402
from app.services.snipeit_ops import SnipeItHandoverService  # noqa: E402

ENGINEER = "probe.engineer@example.test"
REPORT = ROOT / "docs" / "snipeit-integration-report.md"
PNG = b"\x89PNG\r\n\x1a\nprobe-signed-paper"


class Upload:
    filename = "signed-paper.png"

    def __init__(self) -> None:
        self._content = PNG

    async def read(self, size: int = -1) -> bytes:
        content = self._content
        self._content = b""
        return content


class Probe:
    def __init__(self) -> None:
        self.results: list[tuple[int, str, bool, str]] = []

    def record(self, number: int, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((number, name, ok, detail))
        print(
            f"{'PASS' if ok else 'FAIL'} {number:02d} {name}"
            + (f" :: {detail}" if detail and not ok else "")
        )

    def template(self, path: Path) -> None:
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("[Content_Types].xml", b"content types")
            archive.writestr(
                "word/document.xml",
                b"<w:document><w:body><w:p><w:r><w:t>{{ENGINEER}}</w:t></w:r>"
                b"</w:p></w:body></w:document>",
            )
        path.write_bytes(output.getvalue())

    def payload(self, serial: str) -> dict:
        return {
            "serial": serial,
            "username": "probe.user",
            "hostname": "PROBE-PC",
            "manufacturer": "Dell",
            "model": "Latitude",
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
                {
                    "id": "chrome",
                    "name": "Chrome",
                    "installed": True,
                    "version": "120",
                    "method": "registry",
                }
            ],
            "windows_activation": {
                "status": "Licensed",
                "status_code": 1,
                "product_name": "Windows 11 Pro",
            },
        }

    async def run(self) -> int:
        factory = get_sessionmaker()
        client = SnipeItClient(
            os.getenv("SNIPEIT_URL", "").rstrip("/"),
            ServiceAccountProvider(os.getenv("SNIPEIT_TOKEN", "")),
        )
        temp = Path(tempfile.mkdtemp(prefix="v2-handover-probe-"))
        forms = temp / "forms"
        documents = temp / "documents"
        forms.mkdir()
        documents.mkdir()
        self.template(forms / "B.tech.docx")
        config.FORMS_DIR = str(forms)
        config.DOCUMENTS_DIR = str(documents)
        config.REQUIRED_SOFTWARE_IDS = []
        complete_id = None
        ready_id = None
        try:
            ready_label = await client.find_status_label_id("Ready to deploy")
            if ready_label is None:
                raise RuntimeError("Ready to deploy status label not found")

            complete_id = await self.create_case(factory, client, "TEST-SN-0002")
            await self.prepare_checks(
                factory, client, complete_id, "TEST-SN-0002", ready_label
            )

            async with factory() as session:
                service = HandoverService(session)
                users = await service.search_snipeit_users(
                    complete_id, "test.btech1", client=client
                )
                recipient = next(
                    (user for user in users if user["username"] == "test.btech1"),
                    None,
                )
                if recipient is None:
                    raise RuntimeError("test.btech1 not found")
                snipeit_service = SnipeItHandoverService(session)
                await snipeit_service.choose_recipient(
                    complete_id,
                    mode="snipeit",
                    user_id=recipient["id"],
                    actor=ENGINEER,
                    client=client,
                )
                await snipeit_service.confirm_recipient_items(
                    complete_id, actor=ENGINEER, client=client
                )
                await snipeit_service.checkout(
                    complete_id, actor=ENGINEER, client=client
                )
                await session.commit()

            async with factory() as session:
                form = await FormService(session, forms_dir=forms).generate(
                    complete_id,
                    actor=ENGINEER,
                    fallback_engineer_name="Probe Engineer",
                )
                await session.commit()
                with zipfile.ZipFile(BytesIO(form.content)) as archive:
                    document_xml = archive.read("word/document.xml").decode("utf-8")
                self.record(
                    1,
                    "company form contains the engineer name",
                    "Probe Engineer" in document_xml,
                )

            async with factory() as session:
                view = await DocumentService(
                    session,
                    documents_dir=documents,
                    max_bytes=config.DOCUMENT_MAX_BYTES,
                ).store_signed_paper(
                    complete_id,
                    Upload(),
                    actor=ENGINEER,
                    client=client,
                )
                await session.commit()
                stages = {item.stage: item.status for item in view.stages}
                self.record(
                    2,
                    "signed paper records scan and push",
                    stages["document_scanned"] == "passed"
                    and stages["document_pushed"] == "passed",
                    f"stages={stages}",
                )

            asset = await client.get_asset_by_serial("TEST-SN-0002")
            files = await client.list_asset_files(asset.id)
            self.record(
                3,
                "signed paper is attached to the Snipe-IT asset",
                any(file.filename.endswith("signed-paper.png") for file in files),
                f"files={files}",
            )

            async with factory() as session:
                service = HandoverService(session)
                handover = await service.get(complete_id, with_details=True)
                outcome = case_outcome(
                    stage_states(handover),
                    recipient_mode=handover.recipient_mode,
                    cancelled=handover.status == "cancelled",
                )
                await session.commit()
                status_map = {
                    row.stage: row.status for row in handover.stages
                }
                self.record(
                    4,
                    "complete handover outcome is complete",
                    outcome.value == "complete",
                    f"outcome={outcome.value!r} status={handover.status!r} "
                    f"stages={status_map}",
                )

            ready_id = await self.create_case(factory, client, "TEST-SN-0003")
            await self.prepare_checks(
                factory, client, ready_id, "TEST-SN-0003", ready_label
            )
            async with factory() as session:
                service = SnipeItHandoverService(session)
                await service.choose_recipient(
                    ready_id,
                    mode="none",
                    actor=ENGINEER,
                    client=client,
                )
                await session.commit()
                handover = await HandoverService(session).get(
                    ready_id, with_details=True
                )
                outcome = case_outcome(
                    stage_states(handover),
                    recipient_mode=handover.recipient_mode,
                    cancelled=False,
                )
                status_map = {
                    row.stage: row.status for row in handover.stages
                }
                self.record(
                    5,
                    "none recipient outcome is ready",
                    outcome.value == "ready",
                    f"outcome={outcome.value!r} status={handover.status!r} "
                    f"stages={status_map}",
                )
        except Exception as exc:  # noqa: BLE001 - report the real error
            self.record(
                99,
                "probe error",
                False,
                f"{type(exc).__name__}: {exc}",
            )
        finally:
            await self.cleanup(client, factory, complete_id, ready_id)
            await client.aclose()
            shutil.rmtree(temp, ignore_errors=True)

        self.write_report()
        passed = sum(1 for _, _, ok, _ in self.results if ok)
        print(f"\n{passed}/{len(self.results)} PASS")
        return 0 if passed == len(self.results) else 1

    async def create_case(self, factory, client, serial: str):
        async with factory() as session:
            service = HandoverService(session)
            existing = await service.find_active_by_serial(serial)
            if existing is not None:
                await service.cancel(existing.id, actor=ENGINEER)
                await session.commit()
            handover = await service.create(
                device_serial=serial,
                engineer_email=ENGINEER,
                engineer_name="Probe Engineer",
                client=client,
            )
            await session.commit()
            return handover.id

    async def prepare_checks(
        self, factory, client, handover_id, serial: str, ready_label: int
    ) -> None:
        async with factory() as session:
            service = SnipeItHandoverService(session)
            await service.set_device_status(
                handover_id,
                status_label_id=ready_label,
                actor=ENGINEER,
                client=client,
            )
            await session.commit()
        async with factory() as session:
            service = HandoverService(session)
            await service.record_agent_report(
                handover_id, self.payload(serial), actor=ENGINEER
            )
            await session.commit()

    async def cleanup(self, client, factory, *handover_ids) -> None:
        for serial in ("TEST-SN-0002", "TEST-SN-0003"):
            try:
                asset = await client.get_asset_by_serial(serial)
                if asset.assigned_to_id is not None:
                    await client.checkin_asset(asset.id, "Phase 04 probe cleanup")
                ready_label = await client.find_status_label_id("Ready to deploy")
                if ready_label is not None:
                    await client.update_asset_status(asset.id, ready_label)
            except Exception as exc:  # noqa: BLE001
                print(f"cleanup warning: {type(exc).__name__}: {exc}")
        for handover_id in handover_ids:
            if handover_id is None:
                continue
            try:
                async with factory() as session:
                    service = HandoverService(session)
                    handover = await service.get(
                        handover_id, with_details=True
                    )
                    if handover.status == "completed":
                        await session.delete(handover)
                    else:
                        await service.cancel(handover_id, actor=ENGINEER)
                    await session.commit()
            except Exception as exc:  # noqa: BLE001
                print(f"cleanup warning: {type(exc).__name__}: {exc}")

    def write_report(self) -> None:
        rows = "\n".join(
            f"| {number} | {name} | {'PASS' if ok else 'FAIL'} | {detail} |"
            for number, name, ok, detail in self.results
        )
        section = (
            "\n## Phase 04\n\n"
            "| # | Check | Result | Detail |\n|---|---|---|---|\n"
            f"{rows}\n"
        )
        existing = REPORT.read_text(encoding="utf-8") if REPORT.exists() else ""
        marker = "\n## Phase 04\n"
        if marker in existing:
            existing = existing[: existing.index(marker)]
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(existing.rstrip() + "\n" + section, encoding="utf-8")
        print(f"report -> {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(asyncio.run(Probe().run()))
