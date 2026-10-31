"""Pydantic response models for the operations dashboard (Phase 7)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.dto.handover import HandoverSummary, MissingStepOut


class StageCountsOut(BaseModel):
    """One row of the per-stage matrix."""

    passed: int = 0
    pending: int = 0
    blocked: int = 0
    failed: int = 0
    skipped: int = 0


class EngineerCountOut(BaseModel):
    email: str
    name: str = ""
    total: int
    completed: int


class MissingStepCountOut(BaseModel):
    stage: str
    count: int


class DashboardSummaryOut(BaseModel):
    """Everything the KPI tiles and the "what is missing" panel need."""

    created_from: datetime | None = None
    created_to: datetime | None = None
    total: int = 0
    completed: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    stages: dict[str, StageCountsOut] = Field(default_factory=dict)
    average_time_to_complete_seconds: float | None = None
    by_engineer: list[EngineerCountOut] = Field(default_factory=list)
    top_missing_steps: list[MissingStepCountOut] = Field(default_factory=list)


class StageProgressOut(BaseModel):
    """The compact stage indicator shown in the handover table."""

    stage: str
    status: str


class HandoverRowOut(BaseModel):
    handover: HandoverSummary
    stages: list[StageProgressOut]
    missing_steps: list[MissingStepOut]


class HandoverRowListOut(BaseModel):
    items: list[HandoverRowOut]
    total: int
    page: int
    page_size: int
