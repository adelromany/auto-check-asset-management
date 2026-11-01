"""Phase 7: the portal prints the handover form itself.

The owner's requirement is that ``report_printed`` is decided by the print
system, never by a button. These tests drive the real service and the real
HTTP routes against a file-backed SQLite database; only the two blocking
steps (python-docx/LibreOffice/Ghostscript) are replaced by a fake, because
no test host has Word or a printer.

What is real here: the claim (partial unique index), the three-phase
transaction handling, the stage/event writes, the HTTP status mapping, the
PDF download path resolution and the manual-confirmation rules.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.clients.snipeit as snipeit
import app.db.models  # noqa: F401  (registers every table on Base.metadata)
import app.dependencies
import app.main
from app import config
from app.db.base import Base
from app.db.models.handover import PrintAttempt
from app.domain.errors import PrintConflict
from app.domain.print_rules import (
    ALREADY_CONFIRMED_REASON,
    AUTOMATIC_ONLY_REASON,
    CHECKOUT_REQUIRED_REASON,
    PRINTING_DISABLED_REASON,
    RUNNING_REASON,
    STALE_CLAIM_REASON,
    PrintMode,
    PrintState,
)
from app.services import handover_printing
from app.services.sessions import SessionStore
from tests.fakes.snipeit_fake import SnipeItFake

ENGINEER = {"name": "Engineer One", "email": "engineer@example.com"}
PDF = b"%PDF-1.4\n% rendered handover form\n"
ALICE_ID = 1


@dataclass
class PrintHarness:
    app: FastAPI
    client: httpx.AsyncClient
    fake: SnipeItFake
    factory: async_sessionmaker
    output_dir: Path
    renders: list = field(default_factory=list)
    error: list = field(default_factory=list)
    real_render: object = None


def _pdf_bytes(name: str) -> bytes:
    return PDF + name.encode()


@pytest_asyncio.fixture()
async def printing(tmp_path, monkeypatch):
    """A handover portal with a file database and a fake print pipeline."""
    output_dir = tmp_path / "print"
    output_dir.mkdir()
    database = (tmp_path / "print.db").as_posix()

    monkeypatch.setattr(config, "FORM_OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(config, "FORM_TEMPLATE_PATH", str(tmp_path / "absent.docx"))
    monkeypatch.setattr(config, "PRINT_MODE", "spooler")
    monkeypatch.setattr(config, "PRINT_PRINTER", "FakeQueue")
    monkeypatch.setattr(config, "AUTO_PRINT_AFTER_CHECKOUT", True)
    # Never let a developer .env token make the service call a real server.
    monkeypatch.setattr(config, "SNIPEIT_TOKEN", "")

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        # WAL lets two trigger tasks read while one writes; the partial unique
        # index (not the SQLite file lock) then decides the race.
        await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    harness = PrintHarness(
        app=None, client=None, fake=None, factory=factory, output_dir=output_dir,
        real_render=handover_printing.render_and_submit,
    )

    def fake_render(job):
        """Stand in for fill_document + convert_to_pdf + run_ghostscript."""
        harness.renders.append(job)
        if harness.error:
            raise harness.error[0]
        path = output_dir / f"Handover_{job.handover_id}_attempt{job.attempt_no}.pdf"
        path.write_bytes(_pdf_bytes(path.name))
        return {
            "pdf_name": path.name,
            "pdf_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "spooler_accepted": job.mode is PrintMode.SPOOLER,
            "job": {"job_id": 7, "status": "printing"},
            "tokens_missing": [],
            "labels_filled": 3,
        }

    monkeypatch.setattr(handover_printing, "render_and_submit", fake_render)
    monkeypatch.setattr(handover_printing, "get_sessionmaker", lambda: factory)

    application = app.main.create_app()
    store = SessionStore(ttl_seconds=600)
    fake = SnipeItFake()
    http_client = httpx.AsyncClient(transport=fake.transport)
    live_client = snipeit.SnipeItClient(
        "http://snipeit.test",
        snipeit.ServiceAccountProvider(fake.token),
        http_client=http_client,
        engineer_email=ENGINEER["email"],
        retry_backoff=0.0,
    )

    async def override_session():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def override_snipeit_client():
        yield live_client

    application.dependency_overrides[app.dependencies.get_session] = override_session
    application.dependency_overrides[app.dependencies.current_user] = lambda: ENGINEER
    application.dependency_overrides[app.dependencies.get_store] = lambda: store
    application.dependency_overrides[
        app.dependencies.get_snipeit_client
    ] = override_snipeit_client

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        csrf = await client.get("/api/me")
        client.headers["X-CSRF-Token"] = csrf.headers["X-CSRF-Token"]
        harness.app = application
        harness.client = client
        harness.fake = fake
        yield harness

    await http_client.aclose()
    await engine.dispose()


# -- helpers ----------------------------------------------------------------


async def _create(api: PrintHarness, serial: str = "SN-10") -> str:
    response = await api.client.post(
        "/api/handovers", json={"device_serial": serial}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _confirm(api: PrintHarness, handover_id: str, stage: str) -> dict:
    response = await api.client.post(
        f"/api/handovers/{handover_id}/stages/{stage}/confirm"
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _agent_report(
    api: PrintHarness, handover_id: str, serial: str = "SN-10"
) -> None:
    session_response = await api.client.get(
        f"/api/session/new?handover_id={handover_id}"
    )
    code = session_response.json()["code"]
    submit = await api.client.post(
        f"/api/session/{code}/submit",
        json={
            "serial": serial,
            "username": "alice",
            "user_domain": "TESTDOMAIN",
            "console_user": "TESTDOMAIN\\alice",
            "hostname": "PC-1",
            "manufacturer": "Lenovo",
            "model": "ThinkPad T14",
            "cpu": "Intel Core i7",
            "ram_gb": 16,
            "os_name": "Windows 11",
            "disks": [{"name": "NVMe", "size_gb": 512, "type": "SSD"}],
            "software_checks": [
                {"id": software_id, "name": software_id, "installed": True}
                for software_id in ("forticlient", "sccm", "intune", "office2021")
            ],
            "windows_activation": {"status": "Licensed", "status_code": 1},
        },
    )
    assert submit.status_code == 200, submit.text


async def _reported(api: PrintHarness, serial: str = "SN-10") -> str:
    """A case with an agent report, still before the checkout stage."""
    handover_id = await _create(api, serial)
    await _confirm(api, handover_id, "device_prepared")
    await _confirm(api, handover_id, "user_signed_in")
    await _agent_report(api, handover_id, serial)
    return handover_id


async def _ready(api: PrintHarness, serial: str = "SN-10") -> str:
    handover_id = await _reported(api, serial)
    response = await api.client.post(
        f"/api/handovers/{handover_id}/recipient/confirm",
        json={"snipeit_user_id": ALICE_ID},
    )
    assert response.status_code == 200, response.text
    return handover_id


async def _checkout(api: PrintHarness, handover_id: str) -> dict:
    response = await api.client.post(f"/api/handovers/{handover_id}/checkout")
    assert response.status_code == 200, response.text
    return response.json()


async def _set_stage(
    api: PrintHarness, handover_id: str, stage: str, status: str = "passed"
) -> None:
    """Put a stage in a state the API alone cannot reach (test fixture)."""
    from app.repositories.handovers import HandoverRepository

    async with api.factory() as session:
        handover = await HandoverRepository(session).get(
            uuid.UUID(handover_id), with_details=True
        )
        for row in handover.stages:
            if row.stage == stage:
                row.status = status
                row.reason = None
        await session.commit()


async def _insert_attempt(
    api: PrintHarness,
    handover_id: str,
    *,
    attempt_no: int = 1,
    state: str = PrintState.RUNNING.value,
    started_at: datetime | None = None,
    pdf_name: str | None = None,
) -> uuid.UUID:
    attempt = PrintAttempt(
        handover_id=uuid.UUID(handover_id),
        attempt_no=attempt_no,
        mode=PrintMode.SPOOLER.value,
        printer="FakeQueue",
        state=state,
        actor=ENGINEER["email"],
        started_at=started_at or datetime.now(timezone.utc),
        pdf_name=pdf_name,
        detail={},
    )
    async with api.factory() as session:
        session.add(attempt)
        await session.commit()
    return attempt.id


def _stage(body: dict, key: str) -> dict:
    return next(item for item in body["stages"] if item["stage"] == key)


async def _detail(api: PrintHarness, handover_id: str) -> dict:
    response = await api.client.get(f"/api/handovers/{handover_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _event_types(detail: dict) -> list[str]:
    return [event["type"] for event in detail["events"]]


# -- automatic print after checkout ----------------------------------------


async def test_checkout_prints_the_form_automatically(
    printing: PrintHarness,
) -> None:
    handover_id = await _ready(printing)

    _ = await _checkout(printing, handover_id)

    state = await printing.client.get(f"/api/handovers/{handover_id}/print")
    assert state.status_code == 200, state.text
    body = state.json()
    assert body["state"] == "accepted"
    assert body["attempt"] == 1
    assert body["mode"] == "spooler"
    assert body["printer"] == "FakeQueue"
    assert body["pdf_available"] is True
    assert body["manual"] is False

    detail = await _detail(printing, handover_id)
    stage = _stage(detail, "report_printed")
    assert stage["status"] == "passed"
    assert stage["reason"] is None
    assert stage["detail"]["print_state"] == "accepted"
    assert stage["detail"]["print_spooler_accepted"] is True

    types = _event_types(detail)
    assert "print_attempt_started" in types
    assert "print_attempt_accepted" in types

    assert len(printing.renders) == 1
    job = printing.renders[0]
    assert job.data["serial"] == "SN-10"
    assert job.extra["asset_tag"] == "A-10"
    assert job.extra["handover_id"] == handover_id
    assert job.extra["recipient_username"] == "alice"


async def test_auto_print_is_a_setting_not_a_button(
    printing: PrintHarness, monkeypatch
) -> None:
    monkeypatch.setattr(config, "AUTO_PRINT_AFTER_CHECKOUT", False)
    handover_id = await _ready(printing)

    await _checkout(printing, handover_id)

    assert printing.renders == []
    state = (await printing.client.get(
        f"/api/handovers/{handover_id}/print"
    )).json()
    assert state["state"] == "idle"
    assert _stage(await _detail(printing, handover_id), "report_printed")[
        "status"
    ] == "pending"


async def test_a_failed_print_does_not_undo_the_checkout(
    printing: PrintHarness,
) -> None:
    printing.error.append(RuntimeError("the converter crashed"))
    handover_id = await _ready(printing)

    body = await _checkout(printing, handover_id)

    assert _stage(body, "checkout")["status"] == "passed"
    detail = await _detail(printing, handover_id)
    stage = _stage(detail, "report_printed")
    assert stage["status"] == "failed"
    assert stage["reason"]
    assert detail["status"] != "cancelled"


# -- the guard ---------------------------------------------------------------


async def test_print_is_refused_before_checkout(printing: PrintHarness) -> None:
    handover_id = await _reported(printing)

    response = await printing.client.post(f"/api/handovers/{handover_id}/print")

    assert response.status_code == 409
    assert response.json()["detail"] == CHECKOUT_REQUIRED_REASON
    assert printing.renders == []


async def test_print_is_refused_without_an_agent_report(
    printing: PrintHarness,
) -> None:
    handover_id = await _create(printing)
    await _set_stage(printing, handover_id, "checkout")

    response = await printing.client.post(f"/api/handovers/{handover_id}/print")

    assert response.status_code == 409
    assert "agent report" in response.json()["detail"]
    assert printing.renders == []


# -- one attempt at a time ---------------------------------------------------


async def test_a_second_trigger_while_one_is_running_prints_once(
    printing: PrintHarness,
) -> None:
    handover_id = await _ready(printing)
    await _checkout(printing, handover_id)
    assert len(printing.renders) == 1

    again = await printing.client.post(f"/api/handovers/{handover_id}/print")

    assert again.status_code == 409
    assert "already" in again.json()["detail"].lower()
    assert len(printing.renders) == 1


async def test_two_concurrent_triggers_claim_a_single_attempt(
    printing: PrintHarness,
) -> None:
    """Two triggers at the same moment must never print twice."""
    import asyncio

    handover_id = await _ready(printing)
    await _set_stage(printing, handover_id, "checkout")

    service = handover_printing.HandoverPrintService()

    async def trigger():
        return await service.start(uuid.UUID(handover_id), actor="a@example.com")

    results = await asyncio.gather(trigger(), trigger(), return_exceptions=True)
    claims = [item for item in results if not isinstance(item, BaseException)]
    conflicts = [item for item in results if isinstance(item, PrintConflict)]
    assert len(claims) == 1, results
    assert len(conflicts) == 1

    async with printing.factory() as session:
        from app.repositories.print_attempts import PrintAttemptRepository

        attempts = await PrintAttemptRepository(session).latest(
            uuid.UUID(handover_id)
        )
        assert attempts.attempt_no == 1
        assert attempts.state == PrintState.RUNNING.value


async def test_the_database_allows_only_one_running_attempt(
    printing: PrintHarness,
) -> None:
    blocked = await _create(printing, "SN-10")
    await _insert_attempt(printing, blocked, attempt_no=1)

    async with printing.factory() as session:
        session.add(
            PrintAttempt(
                handover_id=uuid.UUID(blocked),
                attempt_no=2,
                mode="spooler",
                printer="FakeQueue",
                state=PrintState.RUNNING.value,
                actor=ENGINEER["email"],
                started_at=datetime.now(timezone.utc),
                detail={},
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()

    # A finished attempt never blocks the next one.
    free = await _create(printing, "SN-11")
    await _insert_attempt(
        printing, free, attempt_no=1, state=PrintState.ACCEPTED.value
    )
    async with printing.factory() as session:
        session.add(
            PrintAttempt(
                handover_id=uuid.UUID(free),
                attempt_no=2,
                mode="spooler",
                state=PrintState.RUNNING.value,
                actor=ENGINEER["email"],
                started_at=datetime.now(timezone.utc),
                detail={},
            )
        )
        await session.flush()
        await session.rollback()


async def test_a_stale_claim_is_reclaimed(printing: PrintHarness) -> None:
    handover_id = await _ready(printing)
    await _set_stage(printing, handover_id, "checkout")
    await _insert_attempt(
        printing,
        handover_id,
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    service = handover_printing.HandoverPrintService()
    view = await service.start(uuid.UUID(handover_id), actor=ENGINEER["email"])
    assert view.attempt_no == 2
    assert view.state is PrintState.RUNNING
    await service.run(uuid.UUID(handover_id), view.attempt_id)
    state = (await printing.client.get(
        f"/api/handovers/{handover_id}/print"
    )).json()
    assert state["state"] == "accepted"
    assert len(printing.renders) == 1


async def test_reading_the_state_expires_a_stale_claim(
    printing: PrintHarness,
) -> None:
    handover_id = await _create(printing)
    await _insert_attempt(
        printing,
        handover_id,
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    state = (await printing.client.get(
        f"/api/handovers/{handover_id}/print"
    )).json()

    assert state["state"] == "failed"
    assert "reclaimed" in state["reason"].lower()
    stage = _stage(await _detail(printing, handover_id), "report_printed")
    assert stage["status"] == "failed"
    assert stage["reason"] == STALE_CLAIM_REASON


# -- failure and retry -------------------------------------------------------


async def test_a_failed_print_can_be_retried(printing: PrintHarness) -> None:
    printing.error.append(RuntimeError("ghostscript exited with 1"))
    handover_id = await _ready(printing)
    await _checkout(printing, handover_id)

    failed = (await printing.client.get(
        f"/api/handovers/{handover_id}/print"
    )).json()
    assert failed["state"] == "failed"
    assert failed["attempt"] == 1
    assert _stage(await _detail(printing, handover_id), "report_printed")[
        "status"
    ] == "failed"

    printing.error.clear()
    retry = await printing.client.post(f"/api/handovers/{handover_id}/print")
    assert retry.status_code == 200, retry.text

    accepted = (await printing.client.get(
        f"/api/handovers/{handover_id}/print"
    )).json()
    assert accepted["state"] == "accepted"
    assert accepted["attempt"] == 2
    detail = await _detail(printing, handover_id)
    assert _stage(detail, "report_printed")["status"] == "passed"
    assert len(printing.renders) == 2


async def test_reprint_starts_a_new_attempt(printing: PrintHarness) -> None:
    handover_id = await _ready(printing)
    await _checkout(printing, handover_id)

    refused = await printing.client.post(f"/api/handovers/{handover_id}/print")
    assert refused.status_code == 409
    assert "reprint" in refused.json()["detail"].lower()

    reprint = await printing.client.post(
        f"/api/handovers/{handover_id}/print", json={"reprint": True}
    )
    assert reprint.status_code == 200, reprint.text
    state = (await printing.client.get(
        f"/api/handovers/{handover_id}/print"
    )).json()
    assert state["state"] == "accepted"
    assert state["attempt"] == 2
    assert len(printing.renders) == 2


async def test_the_stage_passes_only_after_the_attempt_is_accepted(
    printing: PrintHarness, monkeypatch
) -> None:
    monkeypatch.setattr(config, "AUTO_PRINT_AFTER_CHECKOUT", False)
    handover_id = await _ready(printing)
    await _checkout(printing, handover_id)

    service = handover_printing.HandoverPrintService()
    view = await service.start(uuid.UUID(handover_id), actor=ENGINEER["email"])

    running = (await printing.client.get(
        f"/api/handovers/{handover_id}/print"
    )).json()
    assert running["state"] == "running"
    stage = _stage(await _detail(printing, handover_id), "report_printed")
    assert stage["status"] == "pending"

    await service.run(uuid.UUID(handover_id), view.attempt_id)

    accepted = (await printing.client.get(
        f"/api/handovers/{handover_id}/print"
    )).json()
    assert accepted["state"] == "accepted"
    stage = _stage(await _detail(printing, handover_id), "report_printed")
    assert stage["status"] == "passed"


# -- errors are plain and path-free -----------------------------------------


async def test_a_pipeline_error_never_leaks_a_server_path(
    printing: PrintHarness,
) -> None:
    printing.error.append(
        RuntimeError(r"cannot open C:\Program Files\Secret\form.docx")
    )
    handover_id = await _ready(printing)
    await _checkout(printing, handover_id)

    response = await printing.client.get(f"/api/handovers/{handover_id}/print")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "failed"
    assert "C:\\" not in body["reason"]
    assert "Program Files" not in body["reason"]

    detail = await _detail(printing, handover_id)
    assert "Program Files" not in str(detail["events"])
    assert _stage(detail, "report_printed")["reason"]


async def test_a_missing_template_is_a_clear_pipeline_error(
    printing: PrintHarness, monkeypatch
) -> None:
    from app.services.laptop_form import LaptopFormError

    monkeypatch.setattr(
        config, "FORM_TEMPLATE_PATH", str(printing.output_dir / "absent.docx")
    )
    job = handover_printing.PrintJob(
        handover_id=str(uuid.uuid4()),
        attempt_no=1,
        mode=PrintMode.PDF_ONLY,
        printer=None,
    )

    with pytest.raises(LaptopFormError) as raised:
        printing.real_render(job)

    assert "FORM_TEMPLATE_PATH" in str(raised.value)


async def test_spooler_mode_without_a_printer_is_a_clear_503(
    printing: PrintHarness, monkeypatch
) -> None:
    monkeypatch.setattr(config, "PRINT_PRINTER", "")
    handover_id = await _ready(printing)
    await _checkout(printing, handover_id)

    response = await printing.client.post(f"/api/handovers/{handover_id}/print")

    assert response.status_code == 503
    assert "PRINT_PRINTER" in response.json()["detail"]
    assert printing.renders == []


# -- manual confirmation rules ----------------------------------------------


async def test_spooler_mode_refuses_a_manual_confirmation(
    printing: PrintHarness,
) -> None:
    handover_id = await _ready(printing)
    await _checkout(printing, handover_id)

    response = await printing.client.post(
        f"/api/handovers/{handover_id}/print/confirm",
        json={"reason": "The printer is out of toner upstairs."},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == AUTOMATIC_ONLY_REASON


async def test_pdf_only_renders_and_accepts_a_reasoned_confirmation(
    printing: PrintHarness, monkeypatch
) -> None:
    monkeypatch.setattr(config, "PRINT_MODE", "pdf_only")
    handover_id = await _ready(printing)

    await _checkout(printing, handover_id)

    state = (await printing.client.get(
        f"/api/handovers/{handover_id}/print"
    )).json()
    assert state["state"] == "pdf_ready"
    assert state["mode"] == "pdf_only"
    assert state["pdf_available"] is True
    assert state["printer"] is None
    stage = _stage(await _detail(printing, handover_id), "report_printed")
    assert stage["status"] == "pending"
    assert stage["reason"] == PRINTING_DISABLED_REASON

    too_short = await printing.client.post(
        f"/api/handovers/{handover_id}/print/confirm",
        json={"reason": "no"},
    )
    assert too_short.status_code == 422

    confirmed = await printing.client.post(
        f"/api/handovers/{handover_id}/print/confirm",
        json={"reason": "This test server has no printer attached."},
    )
    assert confirmed.status_code == 200, confirmed.text
    detail = confirmed.json()
    stage = _stage(detail, "report_printed")
    assert stage["status"] == "passed"
    assert stage["detail"]["print_manual"] is True
    assert "manual_print_confirmation" in _event_types(detail)

    state = (await printing.client.get(
        f"/api/handovers/{handover_id}/print"
    )).json()
    assert state["manual"] is True
    assert "no printer" in (state["manual_reason"] or "").lower()

    again = await printing.client.post(
        f"/api/handovers/{handover_id}/print/confirm",
        json={"reason": "Confirmed once more just to be sure."},
    )
    assert again.status_code == 409
    assert again.json()["detail"] == ALREADY_CONFIRMED_REASON


async def test_a_queued_attempt_keeps_its_own_mode(
    printing: PrintHarness, monkeypatch
) -> None:
    """Changing PRINT_MODE while a job runs must not relabel that job."""
    monkeypatch.setattr(config, "AUTO_PRINT_AFTER_CHECKOUT", False)
    monkeypatch.setattr(config, "PRINT_MODE", "pdf_only")
    handover_id = await _ready(printing)
    await _checkout(printing, handover_id)

    service = handover_printing.HandoverPrintService()
    view = await service.start(uuid.UUID(handover_id), actor=ENGINEER["email"])
    monkeypatch.setattr(config, "PRINT_MODE", "spooler")
    await service.run(uuid.UUID(handover_id), view.attempt_id)

    state = (await printing.client.get(
        f"/api/handovers/{handover_id}/print"
    )).json()
    assert state["state"] == "pdf_ready"
    assert state["mode"] == "pdf_only"
    assert _stage(await _detail(printing, handover_id), "report_printed")[
        "status"
    ] == "pending"


# -- the PDF download --------------------------------------------------------


async def test_the_pdf_can_be_downloaded(printing: PrintHarness) -> None:
    handover_id = await _ready(printing)
    await _checkout(printing, handover_id)

    response = await printing.client.get(
        f"/api/handovers/{handover_id}/print/pdf"
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert "attempt1" in response.headers["content-disposition"]
    assert "SN-10" in response.headers["content-disposition"]


async def test_the_pdf_download_never_leaves_the_output_directory(
    printing: PrintHarness,
) -> None:
    handover_id = await _ready(printing)
    await _checkout(printing, handover_id)
    (printing.output_dir.parent / "escape.pdf").write_bytes(b"%PDF-1.4\n")

    async with printing.factory() as session:
        from app.repositories.print_attempts import PrintAttemptRepository

        attempt = await PrintAttemptRepository(session).latest(
            uuid.UUID(handover_id)
        )
        attempt.pdf_name = "../escape.pdf"
        await session.commit()

    response = await printing.client.get(
        f"/api/handovers/{handover_id}/print/pdf"
    )

    assert response.status_code == 404


async def test_no_pdf_is_a_404_not_a_server_error(
    printing: PrintHarness,
) -> None:
    handover_id = await _create(printing)

    state = await printing.client.get(f"/api/handovers/{handover_id}/print")
    assert state.status_code == 200
    assert state.json()["state"] == "idle"

    download = await printing.client.get(
        f"/api/handovers/{handover_id}/print/pdf"
    )
    assert download.status_code == 404


# -- endpoints are not open doors -------------------------------------------


async def test_the_print_routes_need_a_session(
    printing: PrintHarness, monkeypatch
) -> None:
    handover_id = await _create(printing)
    # Other tests reload the app with SSO disabled; force the real rule here.
    monkeypatch.setattr(config, "SSO_ENABLED", True)
    override = printing.app.dependency_overrides.pop(
        app.dependencies.current_user
    )
    try:
        response = await printing.client.get(
            f"/api/handovers/{handover_id}/print"
        )
    finally:
        printing.app.dependency_overrides[app.dependencies.current_user] = override

    assert response.status_code == 401


async def test_the_print_routes_need_a_csrf_token(
    printing: PrintHarness, monkeypatch
) -> None:
    handover_id = await _create(printing)
    monkeypatch.setattr(config, "SSO_ENABLED", True)

    response = await printing.client.post(
        f"/api/handovers/{handover_id}/print",
        headers={"X-CSRF-Token": ""},
    )

    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


async def test_a_read_of_the_print_state_is_a_safe_method(
    printing: PrintHarness, monkeypatch
) -> None:
    handover_id = await _create(printing)
    monkeypatch.setattr(config, "SSO_ENABLED", True)

    response = await printing.client.get(
        f"/api/handovers/{handover_id}/print",
        headers={"X-CSRF-Token": ""},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "idle"


# -- the state view ----------------------------------------------------------


async def test_the_state_view_never_contains_a_filesystem_path(
    printing: PrintHarness,
) -> None:
    handover_id = await _ready(printing)
    await _checkout(printing, handover_id)

    state = (await printing.client.get(
        f"/api/handovers/{handover_id}/print"
    )).json()

    rendered = str(state)
    assert str(printing.output_dir) not in rendered
    assert ".pdf" not in rendered
    assert state["pdf_available"] is True


async def test_running_state_is_reported_before_the_work_finishes(
    printing: PrintHarness, monkeypatch
) -> None:
    monkeypatch.setattr(config, "AUTO_PRINT_AFTER_CHECKOUT", False)
    handover_id = await _ready(printing)
    await _checkout(printing, handover_id)
    await _insert_attempt(printing, handover_id)

    state = (await printing.client.get(
        f"/api/handovers/{handover_id}/print"
    )).json()

    assert state["state"] == "running"
    assert state["attempt"] == 1
    stage = _stage(await _detail(printing, handover_id), "report_printed")
    assert stage["reason"] in (None, RUNNING_REASON)
