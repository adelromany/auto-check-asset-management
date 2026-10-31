"""Evidence document routes: printable report, upload, download and push."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.clients.snipeit import SnipeItClient, SnipeItError
from app.dependencies import current_user, get_session, get_snipeit_client
from app.domain.errors import HandoverError
from app.dto.handover import DocumentOut, HandoverDetail
from app.routers.http_errors import (
    handover_detail,
    handover_http_error,
    snipeit_http_error,
)
from app.services.documents import DocumentService

router = APIRouter(prefix="/api/handovers", tags=["documents"])

_TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
_environment = Environment(
    loader=FileSystemLoader(str(_TEMPLATES)),
    autoescape=select_autoescape(["html"]),
)


def _service(session: AsyncSession) -> DocumentService:
    return DocumentService(
        session,
        documents_dir=config.DOCUMENTS_DIR,
        max_bytes=config.DOCUMENT_MAX_BYTES,
    )


@router.get("/{handover_id}/report", response_class=HTMLResponse)
async def printable_report(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    service = _service(session)
    try:
        data = await service.report_data(handover_id)
    except HandoverError as exc:
        raise handover_http_error(exc) from exc

    template = _environment.get_template("handover_report.html")
    return HTMLResponse(
        template.render(handover=data.handover, payload=data.payload)
    )


@router.post("/{handover_id}/document", response_model=DocumentOut)
async def upload_document(
    handover_id: uuid.UUID,
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    service = _service(session)
    try:
        document = await service.store(
            handover_id, file, actor=user["email"]
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return DocumentOut.model_validate(document)


@router.get("/{handover_id}/document")
async def download_document(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    service = _service(session)
    try:
        document = await service.latest(handover_id)
        path = service.file_path(document)
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    return FileResponse(
        path,
        media_type=document.content_type,
        filename=document.original_name,
    )


@router.post("/{handover_id}/document/push", response_model=HandoverDetail)
async def push_document(
    handover_id: uuid.UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> HandoverDetail:
    service = _service(session)
    try:
        view = await service.push(
            handover_id, actor=user["email"], client=client
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeit_http_error(exc) from exc
    return handover_detail(view)
