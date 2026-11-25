"""HTTP translation shared by handover-facing routers.

Routers never contain business rules; this module only maps typed domain and
client errors to status codes and builds the detail DTO.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.clients.snipeit import (
    SnipeItAuthError,
    SnipeItError,
    SnipeItNotFound,
    SnipeItRejected,
    SnipeItUnavailable,
)
from app.domain.errors import (
    AgentReportNotFound,
    CaseStateConflict,
    ClosingConfirmationRequired,
    DeviceNotInSnipeIt,
    DocumentNotFound,
    DocumentTooLarge,
    FormTemplateNotFound,
    HandoverAlreadyExists,
    HandoverCancelled,
    HandoverCompleted,
    HandoverError,
    HandoverNotFound,
    InputMissing,
    InvalidStage,
    MaintenanceCaseExists,
    MaintenanceFieldInvalid,
    MaintenanceLabelNotFound,
    ManualStageRequired,
    NotDoneReasonRequired,
    OperationNotInKind,
    RecipientConfirmationConflict,
    SnipeItUnreachable,
    SoftwareCheckConflict,
    StageNotRunnable,
    UnsupportedDocumentType,
)
from app.dto.handover import HandoverDetail
from app.services.handovers import HandoverDetailView

_CONFLICT_ERRORS = (
    HandoverAlreadyExists,
    HandoverCancelled,
    HandoverCompleted,
    CaseStateConflict,
    ManualStageRequired,
    RecipientConfirmationConflict,
    SoftwareCheckConflict,
    StageNotRunnable,
)
_UNPROCESSABLE_ERRORS = (
    InvalidStage,
    InputMissing,
    NotDoneReasonRequired,
    OperationNotInKind,
    ClosingConfirmationRequired,
    MaintenanceFieldInvalid,
    MaintenanceLabelNotFound,
)


def handover_http_error(exc: HandoverError) -> HTTPException:
    if isinstance(exc, MaintenanceCaseExists):
        return HTTPException(
            status_code=409,
            detail={"message": str(exc), "case_id": exc.case_id},
        )
    if isinstance(
        exc,
        (HandoverNotFound, DocumentNotFound, AgentReportNotFound, FormTemplateNotFound),
    ):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, DeviceNotInSnipeIt):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, SnipeItUnreachable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, _UNPROCESSABLE_ERRORS):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, DocumentTooLarge):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, UnsupportedDocumentType):
        return HTTPException(status_code=415, detail=str(exc))
    if isinstance(exc, _CONFLICT_ERRORS):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def snipeit_http_error(exc: SnipeItError) -> HTTPException:
    """Translate client errors without ever exposing the token."""
    if isinstance(exc, SnipeItUnavailable):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, SnipeItAuthError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, SnipeItNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, SnipeItRejected):
        status = exc.status_code if exc.status_code < 500 else 502
        return HTTPException(status_code=status, detail=str(exc))
    return HTTPException(status_code=502, detail="Snipe-IT request failed.")


def handover_detail(view: HandoverDetailView) -> HandoverDetail:
    return HandoverDetail.from_parts(
        view.handover,
        stages=view.stages,
        missing_steps=view.missing_steps,
        events=view.events,
    )
