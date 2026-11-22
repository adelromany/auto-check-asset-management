"""Add repair priority for maintenance registration.

Revision ID: 0006_maintenance_priority
Revises: 0005_maintenance_cost_warranty
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_maintenance_priority"
down_revision: str | None = "0005_maintenance_cost_warranty"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("maintenance_info") as batch:
        batch.add_column(sa.Column("priority", sa.String(length=20), nullable=True))

    # A fresh board must offer a usable governed vendor/category list before
    # the first repair is registered. Keep these inserts in the migration so
    # existing databases receive the same defaults as new installations.
    for name in ("FixTech",):
        op.execute(
            sa.text(
                "INSERT INTO maintenance_destinations (name, name_key, active) "
                "SELECT :name, :key, :active WHERE NOT EXISTS "
                "(SELECT 1 FROM maintenance_destinations WHERE name_key = :key)"
            ).bindparams(name=name, key=name.casefold(), active=True)
        )
    for name in ("Screen", "Battery", "Keyboard", "Motherboard", "Software", "Other"):
        op.execute(
            sa.text(
                "INSERT INTO diagnosis_categories (name, name_key, active) "
                "SELECT :name, :key, :active WHERE NOT EXISTS "
                "(SELECT 1 FROM diagnosis_categories WHERE name_key = :key)"
            ).bindparams(name=name, key=name.casefold(), active=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("maintenance_info") as batch:
        batch.drop_column("priority")
