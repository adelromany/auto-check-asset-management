"""Pydantic request/response models for the handover API (Phase 2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
