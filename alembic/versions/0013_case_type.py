"""Normalize the user-not-ready handover type.

Revision ID: 0013_case_type
Revises: 0012_vendor_contacts
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_case_type"
down_revision = "0012_vendor_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE handovers SET recipient_mode='pending_user' "
            "WHERE recipient_mode='not_in_snipeit'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE handovers SET recipient_mode='not_in_snipeit' "
            "WHERE recipient_mode='pending_user'"
        )
    )
