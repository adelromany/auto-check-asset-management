"""Independent operations: new statuses, case kind, closing with gaps.

Revision ID: 0003_independent_operations
Revises: 0002_software_check
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_independent_operations"
down_revision: str | None = "0002_software_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_WHERE = "status NOT IN ('completed', 'closed_with_gaps', 'cancelled')"
_OLD_ACTIVE_WHERE = "status NOT IN ('completed', 'cancelled')"


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column(
        "handovers",
        sa.Column("kind", sa.String(length=20), server_default="handover", nullable=False),
    )
    op.add_column(
        "handovers", sa.Column("closed_gaps", _json(), nullable=True)
    )
    op.add_column(
        "handovers", sa.Column("recipient_snipeit_name", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "handovers", sa.Column("recipient_snipeit_email", sa.String(length=320), nullable=True)
    )
    op.create_index("ix_handovers_kind", "handovers", ["kind"])

    # Status migration: ``skipped`` becomes an explicit ``not_done`` and
    # ``blocked`` becomes ``failed`` with its existing reason preserved.
    stages = sa.table(
        "handover_stages",
        sa.column("status", sa.String(20)),
        sa.column("reason", sa.Text()),
        sa.column("detail", sa.JSON()),
    )
    op.execute(
        stages.update()
        .where(stages.c.status == "skipped")
        .values(status="not_done")
    )
    op.execute(
        stages.update()
        .where(stages.c.status == "blocked")
        .values(status="failed")
    )

    # A failed/blocked case used to be stored as ``stalled``. Stalled is now
    # an age-only overlay, so the stored status returns to ``in_progress``.
    handovers = sa.table(
        "handovers",
        sa.column("status", sa.String(20)),
    )
    op.execute(
        handovers.update()
        .where(handovers.c.status == "stalled")
        .values(status="in_progress")
    )

    # closed_with_gaps is inactive: the serial becomes reusable.
    op.drop_index("uq_handovers_active_device_serial", table_name="handovers")
    op.create_index(
        "uq_handovers_active_device_serial",
        "handovers",
        ["device_serial"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_WHERE),
        sqlite_where=sa.text(_ACTIVE_WHERE),
    )


def downgrade() -> None:
    op.drop_index("uq_handovers_active_device_serial", table_name="handovers")
    op.create_index(
        "uq_handovers_active_device_serial",
        "handovers",
        ["device_serial"],
        unique=True,
        postgresql_where=sa.text(_OLD_ACTIVE_WHERE),
        sqlite_where=sa.text(_OLD_ACTIVE_WHERE),
    )

    stages = sa.table(
        "handover_stages",
        sa.column("status", sa.String(20)),
    )
    op.execute(
        stages.update()
        .where(stages.c.status == "not_done")
        .values(status="skipped")
    )
    op.execute(
        stages.update()
        .where(stages.c.status == "failed")
        .values(status="blocked")
    )

    # The old schema has no "closed_with_gaps"; such a case had work left, so
    # it returns to in_progress. Its stored gap list is dropped with the column.
    handovers = sa.table(
        "handovers",
        sa.column("status", sa.String(20)),
    )
    op.execute(
        handovers.update()
        .where(handovers.c.status == "closed_with_gaps")
        .values(status="in_progress")
    )

    op.drop_index("ix_handovers_kind", table_name="handovers")
    with op.batch_alter_table("handovers") as batch:
        batch.drop_column("recipient_snipeit_email")
        batch.drop_column("recipient_snipeit_name")
        batch.drop_column("closed_gaps")
        batch.drop_column("kind")
