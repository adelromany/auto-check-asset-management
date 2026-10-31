"""Phase 6: document storage, download, printable report and push."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.clients.snipeit as snipeit
import app.db.models  # noqa: F401  (registers every table on Base.metadata)
import app.dependencies
import app.main
from app import config
from app.db.base import Base
from app.services.documents import DocumentService
from app.services.sessions import SessionStore
from tests.fakes.snipeit_fake import SnipeItFake

ENGINEER = {"name": "Engineer One", "email": "engineer@example.com"}
PDF = b"%PDF-1.4\n% signed handover sheet\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"png-body"
JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-body"
AGENT_PAYLOAD = {
    "serial": "SN-10",
    "username": "alice",
    "hostname": "PC-1",
    "manufacturer": "Lenovo",
    "model": "ThinkPad T14",
    "cpu": "Intel i7",
    "cpu_cores": 8,
    "ram_gb": 16,
    "os_name": "Windows 11",
    "os_version": "23H2",
    "os_arch": "x64",
    "agent_os": "windows",
    "collected_at": "2026-10-31T10:00:00Z",
    "disks": [{"name": "C:", "size_gb": 512, "type": "SSD"}],
    "ip_addresses": [{"iface": "eth0", "ip": "10.0.0.5"}],
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
        "product_name": "Windows 11 Pro",
        "partial_key": "SECRET-KEY-123",
    },
}


@dataclass
class DocsHarness:
    app: FastAPI
    client: httpx.AsyncClient
    fake: SnipeItFake
    documents_dir: Path


@pytest_asyncio.fixture()
async def docs(tmp_path, monkeypatch):
    documents_dir = tmp_path / "documents"
    monkeypatch.setattr(config, "DOCUMENTS_DIR", str(documents_dir))
    monkeypatch.setattr(config, "DOCUMENT_MAX_BYTES", 10 * 1024 * 1024)

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

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
        yield DocsHarness(
            app=application,
            client=client,
            fake=fake,
            documents_dir=documents_dir,
        )

    await http_client.aclose()
    await engine.dispose()


async def _create(api: DocsHarness, serial: str = "SN-10") -> str:
    response = await api.client.post(
        "/api/handovers", json={"device_serial": serial}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _confirm(api: DocsHarness, handover_id: str, stage: str) -> None:
    response = await api.client.post(
        f"/api/handovers/{handover_id}/stages/{stage}/confirm"
    )
    assert response.status_code == 200, response.text


async def _agent_report(
    api: DocsHarness,
    handover_id: str,
    serial: str,
    payload: dict | None = None,
) -> None:
    session_response = await api.client.get(
        f"/api/session/new?handover_id={handover_id}"
    )
    code = session_response.json()["code"]
    body = dict(payload or AGENT_PAYLOAD)
    body["serial"] = serial
    submit = await api.client.post(
        f"/api/session/{code}/submit", json=body
    )
    assert submit.status_code == 200, submit.text


async def _ready_for_scan(
    api: DocsHarness,
    *,
    serial: str = "SN-10",
    payload: dict | None = None,
) -> str:
    handover_id = await _create(api, serial)
    await _confirm(api, handover_id, "device_prepared")
    await _confirm(api, handover_id, "user_signed_in")
    await _agent_report(api, handover_id, serial, payload)
    await _confirm(api, handover_id, "report_printed")
    await _confirm(api, handover_id, "user_signed")
    return handover_id


async def _upload(
    api: DocsHarness,
    handover_id: str,
    *,
    filename: str = "sheet.pdf",
    content: bytes = PDF,
    content_type: str = "application/pdf",
) -> httpx.Response:
    return await api.client.post(
        f"/api/handovers/{handover_id}/document",
        files={"file": (filename, content, content_type)},
    )


def _stage(body: dict, key: str) -> dict:
    return next(item for item in body["stages"] if item["stage"] == key)


def _post_paths(api: DocsHarness) -> list[str]:
    return [path for method, path, _ in api.fake.calls if method == "POST"]


# -- printable report -------------------------------------------------------


async def test_report_renders_the_stored_agent_report_without_the_partial_key(
    docs: DocsHarness,
) -> None:
    handover_id = await _ready_for_scan(docs)

    response = await docs.client.get(
        f"/api/handovers/{handover_id}/report"
    )

    assert response.status_code == 200, response.text
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert handover_id in body
    assert "PC-1" in body
    assert "Chrome" in body
    assert "Licensed" in body
    assert "Recipient signature" in body
    assert "SECRET-KEY-123" not in body

    detail = (
        await docs.client.get(f"/api/handovers/{handover_id}")
    ).json()
    assert _stage(detail, "document_scanned")["status"] == "pending"


async def test_report_without_an_agent_report_is_404(
    docs: DocsHarness,
) -> None:
    handover_id = await _create(docs)

    response = await docs.client.get(
        f"/api/handovers/{handover_id}/report"
    )

    assert response.status_code == 404


# -- upload -----------------------------------------------------------------


async def test_upload_pdf_stores_a_uuid_file_and_passes_stage_eight(
    docs: DocsHarness,
) -> None:
    handover_id = await _ready_for_scan(docs)

    response = await _upload(docs, handover_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["original_name"] == "sheet.pdf"
    assert body["content_type"] == "application/pdf"
    assert body["size_bytes"] == len(PDF)
    assert body["sha256"] == hashlib.sha256(PDF).hexdigest()

    stored = list(docs.documents_dir.iterdir())
    assert len(stored) == 1
    assert re.fullmatch(r"[0-9a-f]{32}\.pdf", stored[0].name)
    assert stored[0].read_bytes() == PDF

    detail = (
        await docs.client.get(f"/api/handovers/{handover_id}")
    ).json()
    assert _stage(detail, "document_scanned")["status"] == "passed"
    assert detail["events"][-1]["type"] == "document_uploaded"


@pytest.mark.parametrize(
    ("filename", "content", "content_type", "extension"),
    [
        ("sheet.png", PNG, "image/png", ".png"),
        ("sheet.jpg", JPEG, "image/jpeg", ".jpg"),
    ],
)
async def test_upload_accepts_png_and_jpeg_by_magic_bytes(
    docs: DocsHarness,
    filename: str,
    content: bytes,
    content_type: str,
    extension: str,
) -> None:
    handover_id = await _ready_for_scan(docs)

    response = await _upload(
        docs,
        handover_id,
        filename=filename,
        content=content,
        content_type=content_type,
    )

    assert response.status_code == 200, response.text
    stored = list(docs.documents_dir.iterdir())
    assert stored[0].suffix == extension


async def test_upload_rejects_a_renamed_executable(
    docs: DocsHarness,
) -> None:
    handover_id = await _ready_for_scan(docs)

    response = await _upload(
        docs,
        handover_id,
        filename="invoice.pdf",
        content=b"MZ\x90\x00this-is-not-a-pdf",
        content_type="application/pdf",
    )

    assert response.status_code == 415
    assert not docs.documents_dir.exists() or not list(
        docs.documents_dir.iterdir()
    )


async def test_upload_rejects_an_oversize_document(
    docs: DocsHarness, monkeypatch
) -> None:
    handover_id = await _ready_for_scan(docs)
    monkeypatch.setattr(config, "DOCUMENT_MAX_BYTES", 20)

    response = await _upload(
        docs, handover_id, content=PDF + b"x" * 100
    )

    assert response.status_code == 413


async def test_upload_sanitizes_a_traversal_filename(
    docs: DocsHarness,
) -> None:
    handover_id = await _ready_for_scan(docs)

    response = await _upload(
        docs,
        handover_id,
        filename="../../evil.pdf",
    )

    assert response.status_code == 200, response.text
    assert response.json()["original_name"] == "evil.pdf"
    stored = list(docs.documents_dir.iterdir())
    assert len(stored) == 1
    assert re.fullmatch(r"[0-9a-f]{32}\.pdf", stored[0].name)
    assert not (docs.documents_dir.parent / "evil.pdf").exists()


async def test_upload_requires_the_signed_stage(
    docs: DocsHarness,
) -> None:
    handover_id = await _create(docs)

    response = await _upload(docs, handover_id)

    assert response.status_code == 409
    assert "user_signed" in response.json()["detail"]


# -- download ---------------------------------------------------------------


async def test_download_returns_the_stored_bytes(
    docs: DocsHarness,
) -> None:
    handover_id = await _ready_for_scan(docs)
    await _upload(docs, handover_id)

    response = await docs.client.get(
        f"/api/handovers/{handover_id}/document"
    )

    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"].startswith("application/pdf")
    assert "sheet.pdf" in response.headers["content-disposition"]


async def test_download_before_upload_is_404(docs: DocsHarness) -> None:
    handover_id = await _create(docs)

    response = await docs.client.get(
        f"/api/handovers/{handover_id}/document"
    )

    assert response.status_code == 404


async def test_download_requires_authentication(
    docs: DocsHarness, monkeypatch
) -> None:
    handover_id = await _ready_for_scan(docs)
    await _upload(docs, handover_id)
    docs.app.dependency_overrides.pop(
        app.dependencies.current_user, None
    )
    monkeypatch.setattr(config, "SSO_ENABLED", True)

    response = await docs.client.get(
        f"/api/handovers/{handover_id}/document"
    )

    assert response.status_code == 401


def test_file_path_rejects_a_tampered_stored_name(tmp_path) -> None:
    service = DocumentService(
        None, documents_dir=tmp_path, max_bytes=1024
    )

    class Tampered:
        stored_name = "../../evil.pdf"

    with pytest.raises(Exception):
        service.file_path(Tampered())


# -- push to Snipe-IT -------------------------------------------------------


async def test_push_uploads_then_verifies_and_passes_stage_nine(
    docs: DocsHarness,
) -> None:
    handover_id = await _ready_for_scan(docs)
    upload = await _upload(docs, handover_id)
    document = upload.json()
    docs.fake.calls.clear()

    response = await docs.client.post(
        f"/api/handovers/{handover_id}/document/push"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert _stage(body, "document_pushed")["status"] == "passed"
    assert _post_paths(docs) == ["/api/v1/hardware/10/files"]
    assert docs.fake.files[10][0]["filename"] == "sheet.pdf"
    assert docs.fake.files[10][0]["size"] == document["size_bytes"]
    assert body["events"][-1]["type"] == "document_push_attempt"


async def test_push_is_idempotent_after_it_passes(
    docs: DocsHarness,
) -> None:
    handover_id = await _ready_for_scan(docs)
    await _upload(docs, handover_id)
    await docs.client.post(
        f"/api/handovers/{handover_id}/document/push"
    )
    docs.fake.calls.clear()

    second = await docs.client.post(
        f"/api/handovers/{handover_id}/document/push"
    )

    assert second.status_code == 200
    assert _stage(second.json(), "document_pushed")["status"] == "passed"
    assert _post_paths(docs) == []


async def test_push_skips_upload_when_the_file_is_already_listed(
    docs: DocsHarness,
) -> None:
    handover_id = await _ready_for_scan(docs)
    document = (await _upload(docs, handover_id)).json()
    docs.fake.files[10].append(
        {
            "id": 500,
            "filename": "sheet.pdf",
            "size": document["size_bytes"],
        }
    )
    docs.fake.calls.clear()

    response = await docs.client.post(
        f"/api/handovers/{handover_id}/document/push"
    )

    assert response.status_code == 200
    assert _stage(response.json(), "document_pushed")["status"] == "passed"
    assert _post_paths(docs) == []


async def test_push_does_not_require_a_confirmed_recipient(
    docs: DocsHarness,
) -> None:
    handover_id = await _ready_for_scan(docs)
    await _upload(docs, handover_id)

    response = await docs.client.post(
        f"/api/handovers/{handover_id}/document/push"
    )

    assert response.status_code == 200
    assert _stage(response.json(), "document_pushed")["status"] == "passed"


async def test_push_fails_cleanly_when_the_asset_is_unknown_then_retries(
    docs: DocsHarness,
) -> None:
    handover_id = await _ready_for_scan(docs, serial="SN-UNKNOWN")
    await _upload(docs, handover_id)

    failed = await docs.client.post(
        f"/api/handovers/{handover_id}/document/push"
    )

    assert failed.status_code == 200
    stage = _stage(failed.json(), "document_pushed")
    assert stage["status"] == "failed"
    assert stage["reason"] == "Asset serial not found in Snipe-IT"
    assert _post_paths(docs) == []

    docs.fake.assets[13] = {
        **docs.fake.assets[10],
        "id": 13,
        "asset_tag": "A-13",
        "serial": "SN-UNKNOWN",
    }
    docs.fake.files[13] = []

    retried = await docs.client.post(
        f"/api/handovers/{handover_id}/document/push"
    )

    assert retried.status_code == 200
    assert _stage(retried.json(), "document_pushed")["status"] == "passed"


async def test_push_fails_when_the_upload_cannot_be_verified(
    docs: DocsHarness,
) -> None:
    handover_id = await _ready_for_scan(docs)
    await _upload(docs, handover_id)
    docs.fake.upload_records_file = False

    response = await docs.client.post(
        f"/api/handovers/{handover_id}/document/push"
    )

    assert response.status_code == 200
    stage = _stage(response.json(), "document_pushed")
    assert stage["status"] == "failed"
    assert stage["reason"].startswith("Verification failed")
    assert _post_paths(docs) == ["/api/v1/hardware/10/files"]


async def test_push_requires_an_uploaded_document(
    docs: DocsHarness,
) -> None:
    handover_id = await _ready_for_scan(docs)

    response = await docs.client.post(
        f"/api/handovers/{handover_id}/document/push"
    )

    assert response.status_code == 409
    assert "document_scanned" in response.json()["detail"]
