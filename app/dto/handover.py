"""Pydantic request/response models for the handover API (Phase 2)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from app.domain.catalog import Operation
from app.domain.handover_rules import (
    StageState,
    case_outcome,
    case_warnings,
    kind_label,
    missing_parts,
    required_operations,
)
from app.domain.stages import StageStatus

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class AgentReportAttach(BaseModel):
    """Body of ``POST /api/handovers/{id}/attach-report`` (the sync flow)."""

    payload: dict[str, Any]


class HandoverCreate(BaseModel):
    """``POST /api/handovers`` body."""

    device_serial: str = Field(min_length=1, max_length=100)
    ticket_ref: str | None = Field(default=None, max_length=100)
    kind: str = Field(default="handover", pattern="^(handover|maintenance)$")
    mode: Literal["none", "snipeit", "pending_user"] = "snipeit"

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


class ModeRequest(BaseModel):
    mode: Literal["none", "snipeit", "pending_user"]


class SoftwareCheckOverride(BaseModel):
    reason: str = Field(min_length=10, max_length=500)

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not 10 <= len(cleaned) <= 500:
            raise ValueError("reason must be 10–500 characters after trimming")
        return cleaned


class DeviceStatusRequest(BaseModel):
    """The Snipe-IT status label to set on the device (null = read only)."""

    status_label_id: int | None = None


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


class DestinationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    active: bool = True


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    active: bool = True


class MaintenanceInfoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    received_date: date | None = None
    reason_text: str | None = None
    reported_issue: str | None = None
    priority: str | None = None
    condition_notes: str | None = None
    accessories: str | None = None
    diagnosis_category: str | None = None
    diagnosis_note: str | None = None
    destination_id: int | None = None
    vendor: str | None = None
    sent_date: date | None = None
    sent_by: str | None = None
    reference: str | None = None
    expected_return_date: date | None = None
    returned_date: date | None = None
    turnaround_days: int | None = None
    is_overdue: bool = False
    outcome: str | None = None
    outcome_note: str | None = None
    cost: str | None = None
    warranty: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _validate_data(cls, data: Any) -> Any:
        if data is None:
            return None
        if not isinstance(data, dict):
            from app.domain.maintenance_rules import (
                is_overdue as _is_overdue,
                turnaround_days as _turnaround_days,
            )

            today = date.today()
            sent = getattr(data, "sent_date", None)
            exp = getattr(data, "expected_return_date", None)
            ret = getattr(data, "returned_date", None)
            dest = None
            try:
                from sqlalchemy import inspect
                from sqlalchemy.orm.base import NO_VALUE

                ins_d = inspect(data)
                if (
                    ins_d is not None
                    and hasattr(ins_d, "attrs")
                    and hasattr(ins_d.attrs, "destination")
                ):
                    if ins_d.attrs.destination.loaded_value is not NO_VALUE:
                        dest = ins_d.attrs.destination.loaded_value
                else:
                    dest = getattr(data, "destination", None)
            except Exception:
                pass
            vendor_name = dest.name if dest is not None else None
            return {
                "received_date": getattr(data, "received_date", None),
                "reason_text": getattr(data, "reason_text", None),
                "reported_issue": getattr(data, "reported_issue", None),
                "priority": getattr(data, "priority", None),
                "condition_notes": getattr(data, "condition_notes", None),
                "accessories": getattr(data, "accessories", None),
                "diagnosis_category": getattr(data, "diagnosis_category", None),
                "diagnosis_note": getattr(data, "diagnosis_note", None),
                "destination_id": getattr(data, "destination_id", None),
                "vendor": vendor_name,
                "sent_date": sent,
                "sent_by": getattr(data, "sent_by", None),
                "reference": getattr(data, "reference", None),
                "expected_return_date": exp,
                "returned_date": ret,
                "turnaround_days": _turnaround_days(sent_date=sent, returned_date=ret),
                "is_overdue": _is_overdue(
                    sent_date=sent,
                    expected_return_date=exp,
                    today=today,
                    returned=ret is not None,
                ),
                "outcome": getattr(data, "outcome", None),
                "outcome_note": getattr(data, "outcome_note", None),
                "cost": getattr(data, "cost", None),
                "warranty": getattr(data, "warranty", None),
            }
        return data


class MaintenanceUpdate(BaseModel):
    reported_issue: str | None = None
    priority: str | None = Field(default=None, pattern="^(low|normal|high|urgent)$")
    condition_notes: str | None = None
    accessories: str | None = None
    diagnosis_category: str | None = None
    diagnosis_note: str | None = None
    vendor: str | None = None
    destination: str | None = None
    sent_date: date | None = None
    sent_by: str | None = None
    reference: str | None = None
    expected_return_date: date | None = None
    returned_date: date | None = None
    outcome: str | None = None
    outcome_note: str | None = None
    cost: str | None = None
    warranty: str | None = None


def _value(item: Any, key: str) -> Any:
    """Read a field from an ORM row or a plain mapping."""
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _outcome_fields(data: Any) -> dict[str, Any]:
    """Derive outcome, missing parts and warnings from loaded operation rows."""
    stages = data.get("stages") if isinstance(data, dict) else getattr(data, "stages", None)
    recipient_mode = (
        data.get("recipient_mode")
        if isinstance(data, dict)
        else getattr(data, "recipient_mode", None)
    )
    cancelled = (
        data.get("status")
        if isinstance(data, dict)
        else getattr(data, "status", None)
    ) == "cancelled"
    states = [
        StageState(
            Operation(row.stage),
            StageStatus(row.status),
            row.reason,
        )
        for row in (stages or [])
    ]
    company_unknown = any(
        _value(row, "stage") == Operation.RECIPIENT_CHECK.value
        and (_value(row, "detail") or {}).get("warning") == "company_unknown"
        for row in (stages or [])
    )
    warnings = case_warnings(
        _value(data, "device_company"),
        _value(data, "recipient_company"),
        company_unknown=company_unknown,
    )
    return {
        "outcome": case_outcome(
            states, recipient_mode=recipient_mode, cancelled=cancelled
        ).value,
        "missing": missing_parts(states, recipient_mode),
        "mode": "pending_user" if recipient_mode == "not_in_snipeit" else (recipient_mode or "snipeit"),
        "kind_label": kind_label(recipient_mode),
        "required": [operation.value for operation in required_operations(recipient_mode)],
        "warnings": [{"code": item.code, "text": item.text} for item in warnings],
    }


class HandoverSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _extract_from_orm(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {**data, **_outcome_fields(data)}
        try:
            from sqlalchemy import inspect
            from sqlalchemy.orm.base import NO_VALUE

            ins = inspect(data)
            if (
                ins is not None
                and hasattr(ins, "attrs")
                and hasattr(ins.attrs, "maintenance")
            ):
                maint_val = ins.attrs.maintenance.loaded_value
                maint = None if maint_val is NO_VALUE else maint_val
                result = {
                    col.key: getattr(data, col.key)
                    for col in ins.mapper.column_attrs
                }
                result["maintenance"] = maint
                result["stages"] = list(data.stages)
                return {**result, **_outcome_fields(result)}
        except Exception:
            pass
        return data

    id: uuid.UUID
    ticket_ref: str | None = None
    kind: str = "handover"
    status: str
    outcome: str
    missing: list[str]
    warnings: list[dict[str, str]] = Field(default_factory=list)
    maintenance_state: str | None = None
    engineer_email: str
    engineer_name: str
    device_serial: str
    snipeit_asset_id: int | None = None
    snipeit_asset_tag: str | None = None
    device_company: str | None = None
    device_model: str | None = None
    device_category: str | None = None
    snipeit_status_name: str | None = None
    recipient_mode: str | None = None
    mode: str = "snipeit"
    kind_label: str = "Lab + user"
    required: list[str] = Field(default_factory=list)
    recipient_free_name: str | None = None
    recipient_free_email: str | None = None
    recipient_reported_username: str | None = None
    recipient_snipeit_id: int | None = None
    recipient_snipeit_username: str | None = None
    recipient_snipeit_name: str | None = None
    recipient_snipeit_email: str | None = None
    recipient_company: str | None = None
    recipient_confirmed_by: str | None = None
    recipient_confirmed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    closed_gaps: list[dict[str, Any]] | None = None
    maintenance: MaintenanceInfoOut | None = None


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


# -- Independent operations (Part A) ----------------------------------------


class NotDoneRequest(BaseModel):
    """Mark one operation not done. The reason is mandatory (3–300)."""

    reason: str = Field(min_length=3, max_length=300)

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not 3 <= len(cleaned) <= 300:
            raise ValueError("reason must be 3–300 characters after trimming")
        return cleaned


class CloseCaseRequest(BaseModel):
    """Close a case with gaps; ``confirmation`` must be the literal CLOSE."""

    confirmation: str = Field(min_length=1, max_length=20)


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


class SnipeItUserSearchResult(BaseModel):
    """One Snipe-IT user candidate for a handover recipient."""

    id: int
    name: str | None = None
    email: str | None = None
    username: str | None = None
    company: str | None = None
    same_company: bool | None = None


class RecipientSelectionRequest(BaseModel):
    """Choose a Snipe-IT user, no recipient, or a free-form recipient."""

    mode: Literal["snipeit", "none", "not_in_snipeit"]
    user_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _validate_mode_fields(self) -> "RecipientSelectionRequest":
        if self.mode == "snipeit":
            if self.user_id is None:
                raise ValueError("user_id is required for a Snipe-IT recipient.")
        elif self.mode == "not_in_snipeit":
            if not self.name or not self.name.strip():
                raise ValueError("name is required for a recipient not in Snipe-IT.")
            if not self.email or "@" not in self.email.strip():
                raise ValueError("A valid email is required.")
        return self


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


class RecipientItemOut(BaseModel):
    """One Snipe-IT asset currently assigned to the selected recipient."""

    asset_id: int
    asset_tag: str | None = None
    serial: str | None = None
    model: str | None = None
    status: str | None = None


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
