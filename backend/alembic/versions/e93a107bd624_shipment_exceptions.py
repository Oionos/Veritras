"""Durable exception episodes and owner policy; no historical backfill.

Revision ID: e93a107bd624
Revises: c62a904df318
"""

from alembic import op
import sqlalchemy as sa

revision = "e93a107bd624"
down_revision = "c62a904df318"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SELECT pg_advisory_xact_lock(864382024)")
        op.execute(
            "DO $$ BEGIN IF (SELECT version_num FROM alembic_version) IS DISTINCT FROM 'c62a904df318' THEN RAISE EXCEPTION 'Exception migration requires c62a904df318'; END IF; END $$"
        )
    op.create_table(
        "exception_policies",
        sa.Column(
            "shipment_id",
            sa.String(),
            sa.ForeignKey("shipments.shipment_id"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("arrival_enabled", sa.Boolean(), nullable=False),
        sa.Column("inactivity_hours", sa.Float()),
        sa.Column("checkpoint_hours", sa.Float()),
        sa.Column("custody_hours", sa.Float()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(42), nullable=False),
        *[
            sa.CheckConstraint(
                f"{name} IS NULL OR ({name} >= 0.25 AND {name} <= 8760)",
                name=f"ck_exception_policy_{name}",
            )
            for name in ("inactivity_hours", "checkpoint_hours", "custody_hours")
        ],
    )
    op.create_table(
        "exception_evaluations",
        sa.Column("scope", sa.String(64), primary_key=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("block_hash", sa.String(66), nullable=False),
        sa.Column("uncertain_shipments", sa.Integer(), nullable=False),
    )
    op.create_table(
        "shipment_exceptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column(
            "shipment_id",
            sa.String(),
            sa.ForeignKey("shipments.shipment_id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution", sa.String(40)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_by", sa.String(42)),
        sa.Column("acknowledgement_note", sa.String(500)),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('arrival_overdue','checkpoint_inactivity','checkpoint_wait','custody_followup')",
            name="ck_shipment_exception_kind",
        ),
    )
    op.create_index(
        "uq_shipment_exception_open",
        "shipment_exceptions",
        ["scope", "shipment_id", "kind"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
        sqlite_where=sa.text("resolved_at IS NULL"),
    )
    op.create_index(
        "ix_shipment_exception_list",
        "shipment_exceptions",
        ["scope", "resolved_at", "first_observed_at"],
    )


def downgrade():
    op.drop_table("shipment_exceptions")
    op.drop_table("exception_evaluations")
    op.drop_table("exception_policies")
