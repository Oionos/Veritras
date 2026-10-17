"""Deduplicate replayed history events without changing legacy rows.

Revision ID: c72b53d91e04
Revises: b19e8a6c4f20
"""
from alembic import op
import sqlalchemy as sa

revision = "c72b53d91e04"
down_revision = "b19e8a6c4f20"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("checkpoints", "custody_transfers"):
        op.add_column(table, sa.Column("source_event_id", sa.String(255), nullable=True))
        op.create_index(f"ix_{table}_source_event_id", table, ["source_event_id"], unique=True)


def downgrade():
    for table in ("custody_transfers", "checkpoints"):
        op.drop_index(f"ix_{table}_source_event_id", table_name=table)
        op.drop_column(table, "source_event_id")
