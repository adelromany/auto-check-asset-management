"""Add V2 maintenance receipt and reason fields.

Revision ID: 0008_maintenance_v2
Revises: 0007_handover_v2
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_maintenance_v2"
down_revision: str | None = "0007_handover_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REASONS = (
    "Screen",
    "Keyboard",
    "Battery",
    "Charger / power",
    "Won't power on",
    "Overheating",
    "Slow",
    "Disk",
    "RAM",
    "Motherboard",
    "Network",
    "Ports",
    "Speaker / mic / webcam",
    "Hinge / body",
    "Liquid damage",
    "OS / software",
    "BIOS / boot",
    "Other",
)


def upgrade() -> None:
    with op.batch_alter_table("maintenance_info") as batch:
        batch.add_column(sa.Column("received_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("reason_text", sa.String(length=300), nullable=True))

    for name in REASONS:
        op.execute(
            sa.text(
                "INSERT INTO diagnosis_categories (name, name_key, active) "
                "SELECT :name, :key, :active WHERE NOT EXISTS "
                "(SELECT 1 FROM diagnosis_categories WHERE name_key = :key)"
            ).bindparams(name=name, key=name.casefold(), active=True)
        )

    # Canonical Phase 06 state names for existing maintenance rows.
    op.execute(
        sa.text(
            "UPDATE handovers SET maintenance_state = 'with_it' "
            "WHERE maintenance_state = 'needs_maintenance'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE handovers SET maintenance_state = 'at_vendor' "
            "WHERE maintenance_state = 'in_maintenance'"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("maintenance_info") as batch:
        batch.drop_column("reason_text")
        batch.drop_column("received_date")

    op.execute(
        sa.text(
            "UPDATE handovers SET maintenance_state = 'needs_maintenance' "
            "WHERE maintenance_state = 'with_it'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE handovers SET maintenance_state = 'in_maintenance' "
            "WHERE maintenance_state = 'at_vendor'"
        )
    )
