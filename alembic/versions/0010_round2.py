"""Add the recipient company to handovers (Round 2: mismatch is a warning).

Revision ID: 0010_round2
Revises: 0008_maintenance_v2
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_round2"
down_revision: str | None = "0008_maintenance_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("handovers") as batch:
        batch.add_column(sa.Column("recipient_company", sa.String(length=120)))


def downgrade() -> None:
    with op.batch_alter_table("handovers") as batch:
        batch.drop_column("recipient_company")
