"""Enforce one active maintenance case per normalized device serial.

Revision ID: 0011_maintenance_unique_serial
Revises: 0010_round2
Create Date: 2026-11-25 14:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_maintenance_unique_serial"
down_revision = "0010_round2"
branch_labels = None
depends_on = None

_MAINT_ACTIVE_WHERE = (
    "kind = 'maintenance' AND status != 'cancelled' "
    "AND (maintenance_state IS NULL OR maintenance_state != 'returned')"
)


def upgrade() -> None:
    op.create_index(
        "uq_handovers_active_maintenance_serial",
        "handovers",
        [sa.text("lower(device_serial)")],
        unique=True,
        postgresql_where=sa.text(_MAINT_ACTIVE_WHERE),
        sqlite_where=sa.text(_MAINT_ACTIVE_WHERE),
    )


def downgrade() -> None:
    op.drop_index("uq_handovers_active_maintenance_serial", table_name="handovers")
