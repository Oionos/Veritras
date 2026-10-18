"""Nullable shipment planning SLA; lifecycle is derived from canonical journal.

Revision ID: c62a904df318
Revises: b47e203fa951
"""

from alembic import op
import sqlalchemy as sa

revision = "c62a904df318"
down_revision = "b47e203fa951"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SELECT pg_advisory_xact_lock(864382024)")
        op.execute(
            "DO $$ BEGIN IF (SELECT version_num FROM alembic_version) IS DISTINCT FROM 'b47e203fa951' THEN RAISE EXCEPTION 'Shipment SLA migration requires b47e203fa951'; END IF; END $$"
        )
    # No historical SLA is inferred. Canonical journal timestamps already persist
    # departure/delivery and naturally follow reorg recovery without a backfill.
    op.add_column(
        "shipments",
        sa.Column("expected_arrival_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "shipments",
        sa.Column(
            "expected_arrival_recorded_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade():
    op.drop_column("shipments", "expected_arrival_recorded_at")
    op.drop_column("shipments", "expected_arrival_at")
