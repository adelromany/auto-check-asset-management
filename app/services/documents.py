"""Evidence documents: printable report, safe storage, download and push.

File safety is enforced here, not in the router: magic bytes decide the type,
the size limit is enforced while reading, the stored name is a server-side
UUID, and the client's filename is kept only for display.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.snipeit import (
    SnipeItClient,
    SnipeItError,
    SnipeItFile,
    SnipeItNotFound,
)
from app.db.models.handover import Document, Handover
from app.domain.errors import (
    AgentReportNotFound,
    DocumentNotFound,
    DocumentTooLarge,
    StageNotRunnable,
    UnsupportedDocumentType,
)
from app.domain.handover_rules import can_run
from app.domain.stages import Stage, StageStatus
from app.repositories.documents import DocumentRepository
from app.repositories.events import EventRepository
from app.repositories.handovers import HandoverRepository
from app.services.handovers import (
    HandoverDetailView,
    HandoverService,
    ensure_open,
    stage_row,
    stage_states,
)
from app.services.snipeit_ops import snipeit_error_detail, snipeit_error_reason

ASSET_NOT_FOUND_REASON = "Asset serial not found in Snipe-IT"
PUSH_VERIFICATION_FAILED_REASON = (
    "Verification failed: the document is not listed on the asset."
)

_PDF = "application/pdf"
_PNG = "image/png"
_JPEG = "image/jpeg"
_EXTENSIONS = {_PDF: ".pdf", _PNG: ".png", _JPEG: ".jpg"}
_STORED_NAME = re.compile(r"^[0-9a-f]{32}\.(pdf|png|jpg)$")
_CHUNK = 64 * 1024


class UploadedFile(Protocol):
    """The part of FastAPI's UploadFile this service needs (no fastapi import)."""

    filename: str | None

    async def read(self, size: int = -1) -> bytes:
        ...


@dataclass(frozen=True)
class ReportData:
    """Everything the printable report template needs."""

    handover: Handover
    payload: dict[str, Any]


def detect_content_type(content: bytes) -> str | None:
    """Return the allowed type from magic bytes, or None."""
    if content.startswith(b"%PDF-"):
        return _PDF
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return _PNG
    if content.startswith(b"\xff\xd8\xff"):
        return _JPEG
    return None


def sanitize_original_name(name: str | None) -> str:
    """Keep a display name only: no directories, control chars or dot tricks."""
    base = (name or "").replace("\\", "/").split("/")[-1]
    cleaned = "".join(
        char for char in base if char.isprintable() and char not in "\r\n\t"
    ).strip().strip(".")
    if not cleaned:
        return "document"
    return cleaned[:255]


class DocumentService:
    """One document use case per method; the router only maps HTTP."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        documents_dir: str | Path,
        max_bytes: int,
    ):
        self._session = session
        self._documents = DocumentRepository(session)
        self._handovers = HandoverRepository(session)
        self._events = EventRepository(session)
        self._core = HandoverService(session)
        self._documents_dir = Path(documents_dir)
        self._max_bytes = max_bytes

    # -- report -----------------------------------------------------------
    async def report_data(self, handover_id: uuid.UUID) -> ReportData:
        handover = await self._core.get(handover_id, with_details=True)
        report = await self._handovers.latest_agent_report(handover.id)
        if report is None:
            raise AgentReportNotFound(
                "The agent report is not available for this handover yet."
            )
        return ReportData(handover=handover, payload=report.payload)

    # -- upload / download ------------------------------------------------
    async def store(
        self,
        handover_id: uuid.UUID,
        upload: UploadedFile,
        *,
        actor: str,
    ) -> Document:
        handover = await self._core.get(handover_id, with_details=True)
        ensure_open(handover)

        row = stage_row(handover, Stage.DOCUMENT_SCANNED)
        if row.status != StageStatus.PASSED.value:
            allowed, reason = can_run(
                Stage.DOCUMENT_SCANNED, stage_states(handover)
            )
            if not allowed:
                raise StageNotRunnable(reason)

        content = await self._read_limited(upload)
        content_type = detect_content_type(content)
        if content_type is None:
            raise UnsupportedDocumentType(
                "Only PDF, PNG or JPEG documents are accepted."
            )

        document_id = uuid.uuid4()
        stored_name = f"{document_id.hex}{_EXTENSIONS[content_type]}"
        self._documents_dir.mkdir(parents=True, exist_ok=True)
        path = self._documents_dir / stored_name
        path.write_bytes(content)

        document = Document(
            id=document_id,
            handover_id=handover.id,
            kind="signed_sheet",
            stored_name=stored_name,
            original_name=sanitize_original_name(upload.filename),
            content_type=content_type,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            uploaded_by=actor,
        )
        await self._documents.add(document)

        row.status = StageStatus.PASSED.value
        row.reason = None
        row.actor = actor
        row.updated_at = _utcnow()
        row.detail = {
            "document_id": str(document.id),
            "filename": document.original_name,
            "content_type": document.content_type,
            "size_bytes": document.size_bytes,
            "sha256": document.sha256,
        }

        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="document_uploaded",
            detail={
                "document_id": str(document.id),
                "filename": document.original_name,
                "content_type": document.content_type,
                "size_bytes": document.size_bytes,
                "sha256": document.sha256,
            },
        )
        await self._core.recompute_status(handover)
        return document

    async def latest(self, handover_id: uuid.UUID) -> Document:
        handover = await self._core.get(handover_id)
        document = await self._documents.latest_for_handover(handover.id)
        if document is None:
            raise DocumentNotFound("No document was uploaded for this handover.")
        return document

    def file_path(self, document: Document) -> Path:
        """The stored path; rejects any name the service did not generate."""
        if not _STORED_NAME.fullmatch(document.stored_name):
            raise DocumentNotFound("The stored document name is invalid.")
        path = self._documents_dir / document.stored_name
        if not path.is_file():
            raise DocumentNotFound("The stored document file is missing.")
        return path

    # -- push to Snipe-IT (stage 9) ---------------------------------------
    async def push(
        self,
        handover_id: uuid.UUID,
        *,
        actor: str,
        client: SnipeItClient,
    ) -> HandoverDetailView:
        handover = await self._core.get(handover_id, with_details=True)
        row = stage_row(handover, Stage.DOCUMENT_PUSHED)
        if row.status == StageStatus.PASSED.value:
            return await self._core.view(handover)

        ensure_open(handover)
        allowed, reason = can_run(
            Stage.DOCUMENT_PUSHED, stage_states(handover)
        )
        if not allowed:
            raise StageNotRunnable(reason)

        document = await self._documents.latest_for_handover(handover.id)
        if document is None:
            raise DocumentNotFound("No document was uploaded for this handover.")

        try:
            asset = await client.get_asset_by_serial(
                handover.device_serial
            )
        except SnipeItError as exc:
            return await self._fail_push(
                handover,
                reason=(
                    ASSET_NOT_FOUND_REASON
                    if isinstance(exc, SnipeItNotFound)
                    else snipeit_error_reason(exc)
                ),
                actor=actor,
                detail=snipeit_error_detail(exc),
            )

        handover.snipeit_asset_id = asset.id
        handover.snipeit_asset_tag = asset.asset_tag

        try:
            files = await client.list_asset_files(asset.id)
        except SnipeItError as exc:
            return await self._fail_push(
                handover,
                reason=snipeit_error_reason(exc),
                actor=actor,
                detail=snipeit_error_detail(exc),
            )

        if _file_present(files, document):
            return await self._pass_push(
                handover,
                document,
                asset_id=asset.id,
                actor=actor,
                already_present=True,
                snipeit_status=None,
            )

        try:
            content = self.file_path(document).read_bytes()
            result = await client.upload_asset_file(
                asset.id,
                document.original_name,
                content,
                document.content_type,
                _push_note(actor, handover.id),
            )
        except SnipeItError as exc:
            return await self._fail_push(
                handover,
                reason=snipeit_error_reason(exc),
                actor=actor,
                detail=snipeit_error_detail(exc),
            )
        except OSError:
            raise DocumentNotFound("The stored document file is missing.")

        if result.status != "success":
            return await self._fail_push(
                handover,
                reason=(
                    result.message
                    or "Snipe-IT did not confirm the document upload."
                ),
                actor=actor,
                detail={"snipeit_status": result.status_code},
            )

        try:
            after = await client.list_asset_files(asset.id)
        except SnipeItError as exc:
            return await self._fail_push(
                handover,
                reason=(
                    "Verification failed: the asset files could not be "
                    "re-read after the upload."
                ),
                actor=actor,
                detail=snipeit_error_detail(exc),
            )

        if not _file_present(after, document):
            return await self._fail_push(
                handover,
                reason=PUSH_VERIFICATION_FAILED_REASON,
                actor=actor,
                detail={"snipeit_status": result.status_code},
            )

        return await self._pass_push(
            handover,
            document,
            asset_id=asset.id,
            actor=actor,
            already_present=False,
            snipeit_status=result.status_code,
        )

    async def _pass_push(
        self,
        handover: Handover,
        document: Document,
        *,
        asset_id: int,
        actor: str,
        already_present: bool,
        snipeit_status: int | None,
    ) -> HandoverDetailView:
        row = stage_row(handover, Stage.DOCUMENT_PUSHED)
        row.status = StageStatus.PASSED.value
        row.reason = None
        row.actor = actor
        row.updated_at = _utcnow()
        row.detail = {
            "asset_id": asset_id,
            "document_id": str(document.id),
            "filename": document.original_name,
            "size_bytes": document.size_bytes,
            "already_present": already_present,
        }
        document.pushed_to_snipeit_at = _utcnow()
        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="document_push_attempt",
            detail={
                "asset_id": asset_id,
                "outcome": (
                    "already_present" if already_present else "uploaded"
                ),
                "filename": document.original_name,
                "snipeit_status": snipeit_status,
            },
        )
        await self._core.recompute_status(handover)
        return await self._core.view(handover)

    async def _fail_push(
        self,
        handover: Handover,
        *,
        reason: str,
        actor: str,
        detail: dict[str, Any] | None = None,
    ) -> HandoverDetailView:
        row = stage_row(handover, Stage.DOCUMENT_PUSHED)
        row.status = StageStatus.FAILED.value
        row.reason = reason
        row.actor = actor
        row.updated_at = _utcnow()
        row.detail = detail or {}
        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="document_push_attempt",
            detail={"outcome": "failed", "reason": reason, **(detail or {})},
        )
        await self._core.recompute_status(handover)
        return await self._core.view(handover)

    # -- internals --------------------------------------------------------
    async def _read_limited(self, upload: UploadedFile) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await upload.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > self._max_bytes:
                raise DocumentTooLarge(
                    f"Document exceeds the {self._max_bytes}-byte limit."
                )
            chunks.append(chunk)
        return b"".join(chunks)


def _file_present(files: list[SnipeItFile], document: Document) -> bool:
    return any(
        item.filename == document.original_name
        and item.size == document.size_bytes
        for item in files
    )


def _push_note(actor: str, handover_id: uuid.UUID) -> str:
    return (
        f"Signed handover sheet uploaded by {actor} via Handover Portal, "
        f"case {handover_id}"
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
