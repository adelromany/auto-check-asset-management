"""Add the software verification stage to existing handovers.

Revision ID: 0002_software_check
Revises: 0001_initial
Create Date: 2026-10-31
"""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "0002_software_check"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    handovers = sa.table(
        "handovers",
        sa.column("id", sa.Uuid()),
        sa.column("status", sa.String(20)),
    )
    stages = sa.table(
        "handover_stages",
        sa.column("id", sa.Uuid()),
        sa.column("handover_id", sa.Uuid()),
        sa.column("stage", sa.String(40)),
        sa.column("status", sa.String(20)),
        sa.column("reason", sa.Text()),
        sa.column("detail", sa.JSON()),
        sa.column("actor", sa.String(320)),
    )
    existing = sa.select(stages.c.handover_id).where(
        stages.c.stage == "software_check"
    )
    rows = bind.execute(
        sa.select(handovers.c.id, handovers.c.status).where(
            ~handovers.c.id.in_(existing)
        )
    ).all()
    if not rows:
        return

    closed_statuses = {"completed", "cancelled"}
    op.bulk_insert(
        stages,
        [
            {
                "id": uuid.uuid4(),
                "handover_id": row.id,
                "stage": "software_check",
                "status": "skipped" if row.status in closed_statuses else "pending",
                "reason": None,
                "detail": (
                    {"message": "Added after this case was closed"}
                    if row.status in closed_statuses
                    else {}
                ),
                "actor": None,
            }
            for row in rows
        ],
    )


def downgrade() -> None:
    stages = sa.table(
        "handover_stages",
        sa.column("stage", sa.String(40)),
    )
    op.execute(
        sa.delete(stages).where(stages.c.stage == "software_check")
    )
