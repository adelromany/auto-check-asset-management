"""Add print_attempts: one row per attempt to print the handover form.

Revision ID: 0003_print_attempts
Revises: 0002_software_check
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_print_attempts"
down_revision: str | None = "0002_software_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "print_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "handover_id",
            sa.Uuid(),
            sa.ForeignKey("handovers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("printer", sa.String(length=200), nullable=True),
        sa.Column(
            "state", sa.String(length=20), nullable=False, server_default="running"
        ),
        sa.Column("pdf_name", sa.String(length=255), nullable=True),
        sa.Column("pdf_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_class", sa.String(length=60), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=320), nullable=False, server_default=""),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_print_attempts_handover_id", "print_attempts", ["handover_id"]
    )
    # At most one running attempt per handover (SQLite and PostgreSQL both
    # support partial unique indexes; the app already relies on one).
    op.create_index(
        "uq_print_attempts_running",
        "print_attempts",
        ["handover_id"],
        unique=True,
        sqlite_where=sa.text("state = 'running'"),
        postgresql_where=sa.text("state = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("uq_print_attempts_running", table_name="print_attempts")
    op.drop_index("ix_print_attempts_handover_id", table_name="print_attempts")
    op.drop_table("print_attempts")
