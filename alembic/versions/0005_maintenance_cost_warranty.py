"""Add the missing maintenance fields: cost and warranty (HQ Console parity).

Revision ID: 0005_maintenance_cost_warranty
Revises: 0004_maintenance
Create Date: 2026-11-17

The governed HQ Console model tracks the repair cost and whether the repair
ran under warranty; ``maintenance_info`` had neither column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_maintenance_cost_warranty"
down_revision: str | None = "0004_maintenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("maintenance_info") as batch:
        batch.add_column(sa.Column("cost", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("warranty", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("maintenance_info") as batch:
        batch.drop_column("warranty")
        batch.drop_column("cost")
