"""Request and response models for the maintenance API (Phase 06)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MaintenanceCaseCreate(BaseModel):
    serial: str = Field(min_length=1, max_length=100)
    reason_id: int | None = None
    reason_text: str | None = Field(default=None, max_length=300)
    planned_vendor_id: int | None = None

    @field_validator("serial")
    @classmethod
    def _clean_serial(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("serial must not be blank")
        return cleaned

    @field_validator("reason_text")
    @classmethod
    def _clean_reason_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class MaintenanceDeviceLookup(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_id: int
    asset_tag: str | None = None
    serial: str
    model: str | None = None
    company: str | None = None
    status: str | None = None
    assigned_to: str | None = None


class MaintenanceReason(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
