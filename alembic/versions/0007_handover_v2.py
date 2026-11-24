"""Add V2 handover device facts and recipient mode.

Revision ID: 0007_handover_v2
Revises: 0006_maintenance_priority
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_handover_v2"
down_revision: str | None = "0006_maintenance_priority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS: tuple[tuple[str, sa.Integer], ...] = (
    ("device_company", 120),
    ("device_model", 120),
    ("device_category", 120),
    ("snipeit_status_name", 80),
    ("recipient_mode", 20),
    ("recipient_free_name", 200),
    ("recipient_free_email", 200),
)


def upgrade() -> None:
    with op.batch_alter_table("handovers") as batch:
        for name, length in COLUMNS:
            batch.add_column(sa.Column(name, sa.String(length=length), nullable=True))
        batch.create_index("ix_handovers_device_company", ["device_company"])


def downgrade() -> None:
    with op.batch_alter_table("handovers") as batch:
        batch.drop_index("ix_handovers_device_company")
        for name, _length in reversed(COLUMNS):
            batch.drop_column(name)
