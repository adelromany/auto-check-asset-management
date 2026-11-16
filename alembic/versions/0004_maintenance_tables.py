"""Maintenance tables: governed lists and typed maintenance fields.

Revision ID: 0004_maintenance
Revises: 0003_independent_operations
Create Date: 2026-11-16

The ORM model ``app/db/models/maintenance.py`` already gave a maintenance case
its typed fields; this migration creates the matching tables so a migrated
database can load a case with ``selectinload(Handover.maintenance)`` and so a
fresh deployment has the same schema the tests get from ``create_all``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_maintenance"
down_revision: str | None = "0003_independent_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _governed_list(table: str) -> None:
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("name_key", sa.String(length=120), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name_key"),
    )


def upgrade() -> None:
    _governed_list("maintenance_destinations")
    _governed_list("diagnosis_categories")

    op.create_table(
        "maintenance_info",
        sa.Column("handover_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reported_issue", sa.Text(), nullable=True),
        sa.Column("condition_notes", sa.Text(), nullable=True),
        sa.Column("accessories", sa.Text(), nullable=True),
        sa.Column("diagnosis_category", sa.String(length=120), nullable=True),
        sa.Column("diagnosis_note", sa.Text(), nullable=True),
        sa.Column("destination_id", sa.Integer(), nullable=True),
        sa.Column("sent_date", sa.Date(), nullable=True),
        sa.Column("sent_by", sa.String(length=320), nullable=True),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("expected_return_date", sa.Date(), nullable=True),
        sa.Column("returned_date", sa.Date(), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=True),
        sa.Column("outcome_note", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["handover_id"], ["handovers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["destination_id"], ["maintenance_destinations.id"]),
        sa.PrimaryKeyConstraint("handover_id"),
    )
    op.create_index(
        "ix_maintenance_info_destination", "maintenance_info", ["destination_id"]
    )
    op.create_index(
        "ix_maintenance_info_expected_return",
        "maintenance_info",
        ["expected_return_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_maintenance_info_expected_return", table_name="maintenance_info"
    )
    op.drop_index("ix_maintenance_info_destination", table_name="maintenance_info")
    op.drop_table("maintenance_info")
    op.drop_table("diagnosis_categories")
    op.drop_table("maintenance_destinations")
