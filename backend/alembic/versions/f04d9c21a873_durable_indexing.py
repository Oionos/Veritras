"""Add a durable chain journal, canonical block anchors and projection bindings.

Revision ID: f04d9c21a873
Revises: c72b53d91e04
"""

from alembic import op
import sqlalchemy as sa

revision = "f04d9c21a873"
down_revision = "c72b53d91e04"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "indexer_cursors",
        sa.Column("scope", sa.String(64), primary_key=True),
        sa.Column("chain_id", sa.BigInteger(), nullable=False),
        sa.Column("registry_address", sa.String(42), nullable=False),
        sa.Column("tracker_address", sa.String(42), nullable=False),
        sa.Column("start_block", sa.BigInteger(), nullable=False),
        sa.Column("last_processed_block", sa.BigInteger(), nullable=False),
        sa.Column("block_hash", sa.String(66), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "chain_blocks",
        sa.Column("scope", sa.String(64), primary_key=True),
        sa.Column("number", sa.BigInteger(), primary_key=True),
        sa.Column("block_hash", sa.String(66), nullable=False),
    )
    op.create_table(
        "chain_events",
        sa.Column("occurrence_id", sa.String(64), primary_key=True),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(255), nullable=False),
        sa.Column("chain_id", sa.BigInteger(), nullable=False),
        sa.Column("contract_address", sa.String(42), nullable=False),
        sa.Column("transaction_hash", sa.String(66), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=False),
        sa.Column("transaction_index", sa.Integer(), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("block_hash", sa.String(66), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("product_key", sa.String(66), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("canonical", sa.Boolean(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chain_events_event_id", "chain_events", ["event_id"])
    op.create_index(
        "ix_chain_events_replay",
        "chain_events",
        ["scope", "canonical", "block_number", "transaction_index", "log_index"],
    )
    op.create_index("ix_chain_events_product", "chain_events", ["scope", "product_key"])
    op.create_index(
        "uq_chain_events_canonical_event",
        "chain_events",
        ["event_id"],
        unique=True,
        postgresql_where=sa.text("canonical"),
        sqlite_where=sa.text("canonical"),
    )
    op.create_table(
        "indexed_products",
        sa.Column("scope", sa.String(64), primary_key=True),
        sa.Column("product_key", sa.String(66), primary_key=True),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey("products.product_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("baseline", sa.JSON(), nullable=False),
        sa.Column("current_handler", sa.String(42), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
    )


def downgrade():
    # Deliberate operator-only downgrade; never run to roll back application code.
    op.drop_table("indexed_products")
    op.drop_index("uq_chain_events_canonical_event", table_name="chain_events")
    op.drop_index("ix_chain_events_product", table_name="chain_events")
    op.drop_index("ix_chain_events_replay", table_name="chain_events")
    op.drop_index("ix_chain_events_event_id", table_name="chain_events")
    op.drop_table("chain_events")
    op.drop_table("chain_blocks")
    op.drop_table("indexer_cursors")
