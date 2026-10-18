"""Persist untrusted wallet submissions separately from indexed products.

Revision ID: b47e203fa951
Revises: a38f917bd260
"""

from alembic import op
import sqlalchemy as sa

revision = "b47e203fa951"
down_revision = "a38f917bd260"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SELECT pg_advisory_xact_lock(864382024)")
        op.execute(
            "DO $$ BEGIN IF (SELECT version_num FROM alembic_version) IS DISTINCT FROM 'a38f917bd260' THEN RAISE EXCEPTION 'Registration lifecycle migration requires a38f917bd260'; END IF; END $$"
        )
    op.create_table(
        "registration_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey("products.product_id"),
            nullable=False,
        ),
        sa.Column("chain_id", sa.BigInteger(), nullable=False),
        sa.Column("registry_address", sa.String(42), nullable=False),
        sa.Column("submitted_by", sa.String(42), nullable=False),
        sa.Column("tx_hash", sa.String(66), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("registration_payload", sa.JSON(), nullable=False),
        sa.Column("metadata_uri", sa.String(500), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("nonce", sa.BigInteger(), nullable=True),
        sa.Column("replaces_tx_hash", sa.String(66), nullable=True),
        sa.Column("replaced_by", sa.String(66), nullable=True),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("block_hash", sa.String(66), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "chain_id", "tx_hash", name="uq_registration_attempt_chain_tx"
        ),
        sa.CheckConstraint(
            "operation IN ('registration','metadata')",
            name="ck_registration_attempt_operation",
        ),
        sa.CheckConstraint(
            "status IN ('submitted','confirming','indexing','indexed','failed','replaced')",
            name="ck_registration_attempt_status",
        ),
    )
    op.create_index(
        "ix_registration_attempts_product_id", "registration_attempts", ["product_id"]
    )


def downgrade():
    op.drop_table("registration_attempts")
