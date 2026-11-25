"""ORM models for maintenance cases and their governed lists.

Portable types only (Integer, String, Text, Date, Boolean), so the same
schema runs on SQLite and PostgreSQL. The case itself still lives in
``handovers`` (rename deferred, D-69); one ``maintenance_info`` row holds the
typed maintenance fields so they are searchable and reportable.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MaintenanceDestination(Base):
    """A governed list value: where a device is sent for repair.

    Never deleted, only deactivated. ``name_key`` is the casefolded name and
    carries the unique constraint, which makes uniqueness case-insensitive on
    every dialect without a functional index.
    """

    __tablename__ = "maintenance_destinations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class DiagnosisCategory(Base):
    """A governed list value: the diagnosis category of a maintenance case."""

    __tablename__ = "diagnosis_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MaintenanceInfo(Base):
    """The typed maintenance fields of one maintenance case (one row)."""

    __tablename__ = "maintenance_info"
    __table_args__ = (
        Index("ix_maintenance_info_destination", "destination_id"),
        Index("ix_maintenance_info_expected_return", "expected_return_date"),
    )

    handover_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("handovers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    received_date: Mapped[date | None] = mapped_column(Date)
    reason_text: Mapped[str | None] = mapped_column(String(300))
    reported_issue: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str | None] = mapped_column(String(20))
    condition_notes: Mapped[str | None] = mapped_column(Text)
    accessories: Mapped[str | None] = mapped_column(Text)
    diagnosis_category: Mapped[str | None] = mapped_column(String(120))
    diagnosis_note: Mapped[str | None] = mapped_column(Text)
    destination_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("maintenance_destinations.id")
    )
    sent_date: Mapped[date | None] = mapped_column(Date)
    sent_by: Mapped[str | None] = mapped_column(String(320))
    reference: Mapped[str | None] = mapped_column(String(100))
    expected_return_date: Mapped[date | None] = mapped_column(Date)
    returned_date: Mapped[date | None] = mapped_column(Date)
    outcome: Mapped[str | None] = mapped_column(String(40))
    outcome_note: Mapped[str | None] = mapped_column(Text)
    cost: Mapped[str | None] = mapped_column(String(100))
    warranty: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    destination: Mapped[MaintenanceDestination | None] = relationship(lazy="selectin")
    handover: Mapped["Handover"] = relationship(back_populates="maintenance")

    @property
    def vendor(self) -> MaintenanceDestination | None:
        return self.destination

    @property
    def vendor_id(self) -> int | None:
        return self.destination_id

    @vendor_id.setter
    def vendor_id(self, value: int | None) -> None:
        self.destination_id = value


# Semantic aliases for review vocabulary
MaintenanceVendor = MaintenanceDestination
IssueCategory = DiagnosisCategory
