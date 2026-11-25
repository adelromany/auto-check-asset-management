"""Add maintenance vendor contact details.

Revision ID: 0012_vendor_contacts
Revises: 0011_maintenance_unique_serial
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_vendor_contacts"
down_revision: str | None = "0011_maintenance_unique_serial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("maintenance_destinations") as batch:
        batch.add_column(sa.Column("contact_name", sa.String(length=120)))
        batch.add_column(sa.Column("phone", sa.String(length=40)))
        batch.add_column(sa.Column("email", sa.String(length=200)))
        batch.add_column(sa.Column("notes", sa.String(length=500)))
    op.create_index(
        "uq_maintenance_destinations_name_lower",
        "maintenance_destinations",
        [sa.text("lower(name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_maintenance_destinations_name_lower",
        table_name="maintenance_destinations",
    )
    with op.batch_alter_table("maintenance_destinations") as batch:
        batch.drop_column("notes")
        batch.drop_column("email")
        batch.drop_column("phone")
        batch.drop_column("contact_name")
