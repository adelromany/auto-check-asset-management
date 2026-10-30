"""Initial handover schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "handovers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_ref", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("engineer_email", sa.String(length=320), nullable=False),
        sa.Column("engineer_name", sa.String(length=200), nullable=False),
        sa.Column("device_serial", sa.String(length=100), nullable=False),
        sa.Column("snipeit_asset_id", sa.Integer(), nullable=True),
        sa.Column("snipeit_asset_tag", sa.String(length=100), nullable=True),
        sa.Column("recipient_reported_username", sa.String(length=200), nullable=True),
        sa.Column("recipient_snipeit_id", sa.Integer(), nullable=True),
        sa.Column("recipient_snipeit_username", sa.String(length=200), nullable=True),
        sa.Column("recipient_confirmed_by", sa.String(length=320), nullable=True),
        sa.Column("recipient_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_handovers_status", "handovers", ["status"])
    op.create_index("ix_handovers_created_at", "handovers", ["created_at"])
    op.create_index("ix_handovers_engineer_email", "handovers", ["engineer_email"])
    op.create_index("ix_handovers_device_serial", "handovers", ["device_serial"])
    op.create_index(
        "uq_handovers_active_device_serial",
        "handovers",
        ["device_serial"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('completed', 'cancelled')"),
        sqlite_where=sa.text("status NOT IN ('completed', 'cancelled')"),
    )

    op.create_table(
        "handover_stages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("handover_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("detail", _json(), nullable=False),
        sa.Column("actor", sa.String(length=320), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["handover_id"], ["handovers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "handover_id", "stage", name="uq_handover_stages_handover_id_stage"
        ),
    )
    op.create_index("ix_handover_stages_handover_id", "handover_stages", ["handover_id"])

    op.create_table(
        "agent_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("handover_id", sa.Uuid(), nullable=False),
        sa.Column("payload", _json(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["handover_id"], ["handovers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_reports_handover_id", "agent_reports", ["handover_id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("handover_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), server_default="signed_sheet", nullable=False),
        sa.Column("stored_name", sa.String(length=255), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.String(length=320), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("pushed_to_snipeit_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["handover_id"], ["handovers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_handover_id", "documents", ["handover_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("handover_id", sa.Uuid(), nullable=False),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=320), nullable=False),
        sa.Column("type", sa.String(length=60), nullable=False),
        sa.Column("detail", _json(), nullable=False),
        sa.ForeignKeyConstraint(["handover_id"], ["handovers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_handover_id_at", "events", ["handover_id", "at"])


def downgrade() -> None:
    op.drop_index("ix_events_handover_id_at", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_documents_handover_id", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_agent_reports_handover_id", table_name="agent_reports")
    op.drop_table("agent_reports")
    op.drop_index("ix_handover_stages_handover_id", table_name="handover_stages")
    op.drop_table("handover_stages")
    op.drop_index("uq_handovers_active_device_serial", table_name="handovers")
    op.drop_index("ix_handovers_device_serial", table_name="handovers")
    op.drop_index("ix_handovers_engineer_email", table_name="handovers")
    op.drop_index("ix_handovers_created_at", table_name="handovers")
    op.drop_index("ix_handovers_status", table_name="handovers")
    op.drop_table("handovers")
