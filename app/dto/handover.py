"""Pydantic request/response models for the handover API (Phase 2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class HandoverCreate(BaseModel):
    """``POST /api/handovers`` body."""

    device_serial: str = Field(min_length=1, max_length=100)
    ticket_ref: str | None = Field(default=None, max_length=100)

    @field_validator("device_serial")
    @classmethod
    def _clean_serial(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("device_serial must not be blank")
        return cleaned

    @field_validator("ticket_ref")
    @classmethod
    def _clean_ticket_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class SoftwareCheckOverride(BaseModel):
    reason: str = Field(min_length=10, max_length=500)

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not 10 <= len(cleaned) <= 500:
            raise ValueError("reason must be 10–500 characters after trimming")
        return cleaned


class StageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: str
    status: str
    reason: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    actor: str | None = None
    updated_at: datetime


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    at: datetime
    actor: str
    type: str
    detail: dict[str, Any] = Field(default_factory=dict)


class MissingStepOut(BaseModel):
    stage: str
    status: str
    reason: str | None = None
    hint: str


class HandoverSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_ref: str | None = None
    status: str
    engineer_email: str
    engineer_name: str
    device_serial: str
    snipeit_asset_id: int | None = None
    snipeit_asset_tag: str | None = None
    recipient_reported_username: str | None = None
    recipient_snipeit_id: int | None = None
    recipient_snipeit_username: str | None = None
    recipient_confirmed_by: str | None = None
    recipient_confirmed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None


class HandoverDetail(HandoverSummary):
    stages: list[StageOut]
    missing_steps: list[MissingStepOut]
    events: list[EventOut]

    @classmethod
    def from_parts(
        cls,
        handover: Any,
        *,
        stages: list[Any],
        missing_steps: list[dict[str, Any]],
        events: list[Any],
    ) -> "HandoverDetail":
        summary = HandoverSummary.model_validate(handover)
        return cls(
            **summary.model_dump(),
            stages=[StageOut.model_validate(stage) for stage in stages],
            missing_steps=[MissingStepOut(**item) for item in missing_steps],
            events=[EventOut.model_validate(event) for event in events],
        )


class HandoverList(BaseModel):
    items: list[HandoverSummary]
    total: int
    page: int
    page_size: int


# -- Phase 5: Snipe-IT write operations -------------------------------------


class RecipientCandidate(BaseModel):
    """One Snipe-IT user the engineer can pick as the recipient."""

    id: int
    username: str | None = None
    name: str | None = None
    email: str | None = None
    matches_reported: bool = False
    matches_engineer: bool = False


class RecipientSearchResult(BaseModel):
    query: str
    candidates: list[RecipientCandidate]
    reported_username: str | None = None
    warning: str | None = None
    detected_user: str | None = None
    is_local: bool = False
    same_as_engineer: bool = False


class RecipientConfirm(BaseModel):
    """Either pick a Snipe-IT user id, or declare "not in Snipe-IT"."""

    snipeit_user_id: int | None = Field(default=None, ge=1)
    not_found: bool = False
    acknowledge_same_as_engineer: bool = False

    @model_validator(mode="after")
    def _exactly_one_choice(self) -> "RecipientConfirm":
        if self.not_found and self.snipeit_user_id is not None:
            raise ValueError(
                "Provide snipeit_user_id or not_found=true, not both."
            )
        if not self.not_found and self.snipeit_user_id is None:
            raise ValueError(
                "Provide snipeit_user_id, or not_found=true when the "
                "recipient is not in Snipe-IT."
            )
        return self


class PreviewCall(BaseModel):
    """One Snipe-IT write the portal would make for this handover."""

    action: str  # "checkout" | "checkin"
    asset_id: int | None = None
    asset_tag: str | None = None
    serial: str | None = None
    target_user_id: int | None = None
    target_user_name: str | None = None
    description: str


class HandoverPreview(BaseModel):
    handover_id: uuid.UUID
    checkout_stage_status: str
    recipient_confirmed: bool
    already_passed: bool = False
    calls: list[PreviewCall] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CheckinRequest(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=50)

    @field_validator("asset_ids")
    @classmethod
    def _unique_positive_ids(cls, value: list[int]) -> list[int]:
        seen: set[int] = set()
        cleaned: list[int] = []
        for asset_id in value:
            if asset_id < 1:
                raise ValueError("asset_ids must contain positive integers")
            if asset_id not in seen:
                seen.add(asset_id)
                cleaned.append(asset_id)
        return cleaned


class CheckinOutcome(BaseModel):
    asset_id: int
    status: str
    asset_tag: str | None = None
    serial: str | None = None
    message: str | None = None


class CheckinResult(BaseModel):
    handover_id: uuid.UUID
    results: list[CheckinOutcome]


# -- Phase 6: documents -----------------------------------------------------


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_name: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_by: str
    uploaded_at: datetime
    pushed_to_snipeit_at: datetime | None = None


# -- Phase 7: automatic printing of the handover form ----------------------


class HandoverPrintRequest(BaseModel):
    """``POST /api/handovers/{id}/print`` body."""

    reprint: bool = False


class ManualPrintConfirmation(BaseModel):
    """``POST /api/handovers/{id}/print/confirm`` body (pdf_only mode only)."""

    reason: str = Field(min_length=10, max_length=500)

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not 10 <= len(cleaned) <= 500:
            raise ValueError("reason must be 10–500 characters after trimming")
        return cleaned


class HandoverPrintState(BaseModel):
    """The print state of one handover: idle, running, accepted, failed or PDF."""

    handover_id: uuid.UUID
    stage: str = "report_printed"
    state: str
    mode: str
    printer: str | None = None
    attempt: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    reason: str | None = None
    pdf_available: bool = False
    manual: bool = False
    manual_reason: str | None = None
    job: dict[str, Any] | None = None

    @classmethod
    def from_view(cls, view: Any) -> "HandoverPrintState":
        return cls(
            handover_id=view.handover_id,
            state=view.state.value,
            mode=view.mode.value,
            printer=view.printer,
            attempt=view.attempt_no,
            started_at=view.started_at,
            finished_at=view.finished_at,
            reason=view.reason,
            pdf_available=view.pdf_available,
            manual=view.manual,
            manual_reason=view.manual_reason,
            job=view.job,
        )
