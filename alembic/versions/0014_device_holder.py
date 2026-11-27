"""Store the latest known device holder on each case.

Revision ID: 0014_device_holder
Revises: 0013_case_type
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_device_holder"
down_revision = "0013_case_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("handovers") as batch:
        batch.add_column(sa.Column("device_holder_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("device_holder_name", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("handovers") as batch:
        batch.drop_column("device_holder_name")
        batch.drop_column("device_holder_id")
