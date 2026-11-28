"""Recurring pending-user lookup fields."""
import sqlalchemy as sa
from alembic import op

revision = "0016_pending_user"
down_revision = "0015_active_per_kind"
branch_labels = None
depends_on = None


def _restore_indexes() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_handovers_active_device_serial "
        "ON handovers (kind, lower(device_serial)) WHERE status NOT IN "
        "('completed', 'closed_with_gaps', 'cancelled')"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_handovers_active_maintenance_serial "
        "ON handovers (lower(device_serial)) WHERE kind = 'maintenance' "
        "AND status != 'cancelled' AND (maintenance_state IS NULL "
        "OR maintenance_state != 'returned')"
    )


def upgrade() -> None:
    with op.batch_alter_table("handovers") as batch:
        batch.add_column(sa.Column("recipient_employee_code", sa.String(60), nullable=True))
        batch.add_column(sa.Column("recipient_username", sa.String(120), nullable=True))
        batch.add_column(sa.Column("pending_checked_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("pending_found_at", sa.DateTime(timezone=True), nullable=True))
    _restore_indexes()


def downgrade() -> None:
    with op.batch_alter_table("handovers") as batch:
        for column in ("pending_found_at", "pending_checked_at", "recipient_username", "recipient_employee_code"):
            batch.drop_column(column)
    _restore_indexes()
