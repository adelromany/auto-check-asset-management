"""Allow one active handover and one active maintenance case per serial."""
from alembic import op
import sqlalchemy as sa

revision = "0015_active_per_kind"
down_revision = "0014_device_holder"
branch_labels = None
depends_on = None

_ACTIVE = sa.text("status NOT IN ('completed', 'closed_with_gaps', 'cancelled')")


def upgrade() -> None:
    op.drop_index("uq_handovers_active_device_serial", table_name="handovers")
    op.create_index(
        "uq_handovers_active_device_serial", "handovers",
        ["kind", sa.text("lower(device_serial)")], unique=True,
        sqlite_where=_ACTIVE, postgresql_where=_ACTIVE,
    )
    # Rebuild the maintenance expression index if an earlier batch rebuild lost it.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_handovers_active_maintenance_serial "
        "ON handovers (lower(device_serial)) WHERE kind = 'maintenance' "
        "AND status != 'cancelled' AND (maintenance_state IS NULL "
        "OR maintenance_state != 'returned')"
    )


def downgrade() -> None:
    # Older batch table rebuilds may already have removed this expression index.
    op.execute("DROP INDEX IF EXISTS uq_handovers_active_maintenance_serial")
    op.execute("DROP INDEX IF EXISTS uq_handovers_active_device_serial")
    op.create_index(
        "uq_handovers_active_device_serial", "handovers", ["device_serial"], unique=True,
        sqlite_where=_ACTIVE, postgresql_where=_ACTIVE,
    )
    maintenance_active = sa.text(
        "kind = 'maintenance' AND status != 'cancelled' "
        "AND (maintenance_state IS NULL OR maintenance_state != 'returned')"
    )
    op.create_index(
        "uq_handovers_active_maintenance_serial", "handovers",
        [sa.text("lower(device_serial)")], unique=True,
        sqlite_where=maintenance_active, postgresql_where=maintenance_active,
    )
