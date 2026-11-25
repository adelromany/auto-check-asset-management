"""Request and response models for the maintenance API (Phase 06)."""

from __future__ import annotations

import uuid
from datetime import date

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


class MaintenanceBatchSend(BaseModel):
    case_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    vendor_id: int
    sent_date: date


class MaintenanceBatchReceive(BaseModel):
    case_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    returned_date: date


class MaintenanceBatchResult(BaseModel):
    case_id: uuid.UUID
    ok: bool
    error: str | None = None


class MaintenanceVendorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    contact_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("name must be at least 2 characters")
        return cleaned

    @field_validator("email")
    @classmethod
    def _email_has_at(cls, value: str | None) -> str | None:
        cleaned = value.strip() if value is not None else None
        if cleaned and "@" not in cleaned:
            raise ValueError("email must contain @")
        return cleaned or None


class MaintenanceVendor(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None
    is_active: bool
    at_vendor_now: int = 0
    total_sent: int = 0
    returned_total: int = 0
    overdue_now: int = 0
    avg_days: float | None = None
    can_delete: bool = True


class MaintenanceVendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    contact_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _clean_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("name must be at least 2 characters")
        return cleaned

    @field_validator("email")
    @classmethod
    def _optional_email_has_at(cls, value: str | None) -> str | None:
        cleaned = value.strip() if value is not None else None
        if cleaned and "@" not in cleaned:
            raise ValueError("email must contain @")
        return cleaned or None


class MaintenanceReason(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
