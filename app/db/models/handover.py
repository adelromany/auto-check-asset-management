"""ORM models for handovers, their stages, evidence, documents and events.

Portable column types only (Uuid, DateTime(timezone=True), JSON with a JSONB
variant on PostgreSQL), so the same schema runs on SQLite and PostgreSQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_type() -> JSON:
    """JSON on every dialect, JSONB on PostgreSQL."""
    return JSON().with_variant(JSONB(), "postgresql")


class Handover(Base):
    """One case of giving one device to one employee."""

    __tablename__ = "handovers"
    __table_args__ = (
        Index("ix_handovers_status", "status"),
        Index("ix_handovers_created_at", "created_at"),
        Index("ix_handovers_engineer_email", "engineer_email"),
        Index("ix_handovers_device_serial", "device_serial"),
        Index("ix_handovers_kind", "kind"),
        # One ACTIVE case per device serial and kind. "Active" means not
        # completed, not closed with gaps and not cancelled; both partial-index
        # predicates are declared so the rule holds on PostgreSQL and SQLite.
        Index(
            "uq_handovers_active_device_serial",
            "kind",
            text("lower(device_serial)"),
            unique=True,
            postgresql_where=text(
                "status NOT IN ('completed', 'closed_with_gaps', 'cancelled')"
            ),
            sqlite_where=text(
                "status NOT IN ('completed', 'closed_with_gaps', 'cancelled')"
            ),
        ),
        Index(
            "uq_handovers_active_maintenance_serial",
            text("lower(device_serial)"),
            unique=True,
            postgresql_where=text(
                "kind = 'maintenance' AND status != 'cancelled' AND (maintenance_state IS NULL OR maintenance_state != 'returned')"
            ),
            sqlite_where=text(
                "kind = 'maintenance' AND status != 'cancelled' AND (maintenance_state IS NULL OR maintenance_state != 'returned')"
            ),
        ),
        Index("ix_handovers_maintenance_state", "maintenance_state"),
        Index("ix_handovers_device_company", "device_company"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_ref: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="handover", server_default="handover"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    maintenance_state: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    engineer_email: Mapped[str] = mapped_column(String(320), nullable=False)
    engineer_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    device_serial: Mapped[str] = mapped_column(String(100), nullable=False)
    snipeit_asset_id: Mapped[int | None] = mapped_column(Integer)
    snipeit_asset_tag: Mapped[str | None] = mapped_column(String(100))
    device_company: Mapped[str | None] = mapped_column(String(120))
    device_model: Mapped[str | None] = mapped_column(String(120))
    device_category: Mapped[str | None] = mapped_column(String(120))
    snipeit_status_name: Mapped[str | None] = mapped_column(String(80))
    device_holder_id: Mapped[int | None] = mapped_column(Integer)
    device_holder_name: Mapped[str | None] = mapped_column(String(200))
    recipient_mode: Mapped[str | None] = mapped_column(String(20))
    recipient_free_name: Mapped[str | None] = mapped_column(String(200))
    recipient_free_email: Mapped[str | None] = mapped_column(String(200))
    recipient_reported_username: Mapped[str | None] = mapped_column(String(200))
    recipient_snipeit_id: Mapped[int | None] = mapped_column(Integer)
    recipient_snipeit_username: Mapped[str | None] = mapped_column(String(200))
    recipient_snipeit_name: Mapped[str | None] = mapped_column(String(200))
    recipient_snipeit_email: Mapped[str | None] = mapped_column(String(320))
    recipient_company: Mapped[str | None] = mapped_column(String(120))
    recipient_employee_code: Mapped[str | None] = mapped_column(String(60))
    recipient_username: Mapped[str | None] = mapped_column(String(120))
    pending_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending_found_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recipient_confirmed_by: Mapped[str | None] = mapped_column(String(320))
    recipient_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_gaps: Mapped[list[dict[str, Any]] | None] = mapped_column(_json_type())

    @property
    def logged_on_user(self) -> str | None:
        if not self.agent_reports:
            return None
        latest = max(self.agent_reports, key=lambda report: (report.received_at, report.id))
        return latest.payload.get("logged_on_user")

    stages: Mapped[list["HandoverStage"]] = relationship(
        back_populates="handover",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    agent_reports: Mapped[list["AgentReport"]] = relationship(
        back_populates="handover",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="handover",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events: Mapped[list["Event"]] = relationship(
        back_populates="handover",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    maintenance: Mapped["MaintenanceInfo | None"] = relationship(
        back_populates="handover",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        lazy="selectin",
    )


class HandoverStage(Base):
    """One verifiable operation of a case; ten for handover, five for maintenance."""

    __tablename__ = "handover_stages"
    __table_args__ = (
        UniqueConstraint(
            "handover_id", "stage", name="uq_handover_stages_handover_id_stage"
        ),
        Index("ix_handover_stages_handover_id", "handover_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    handover_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    reason: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(
        _json_type(), nullable=False, default=dict
    )
    actor: Mapped[str | None] = mapped_column(String(320))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    handover: Mapped[Handover] = relationship(back_populates="stages")


class AgentReport(Base):
    """Redacted agent report, stored as evidence (never the partial key)."""

    __tablename__ = "agent_reports"
    __table_args__ = (Index("ix_agent_reports_handover_id", "handover_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    handover_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(_json_type(), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    handover: Mapped[Handover] = relationship(back_populates="agent_reports")


class Document(Base):
    """A stored evidence file (the scanned signed sheet)."""

    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_handover_id", "handover_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    handover_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(
        String(30), nullable=False, default="signed_sheet", server_default="signed_sheet"
    )
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(320), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    pushed_to_snipeit_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    handover: Mapped[Handover] = relationship(back_populates="documents")


class Event(Base):
    """Append-only business audit trail. No update or delete path exists."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_handover_id_at", "handover_id", "at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    handover_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    actor: Mapped[str] = mapped_column(String(320), nullable=False)
    type: Mapped[str] = mapped_column(String(60), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(
        _json_type(), nullable=False, default=dict
    )

    handover: Mapped[Handover] = relationship(back_populates="events")
