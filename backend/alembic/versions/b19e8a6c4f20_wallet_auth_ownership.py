"""Persist sign-in challenges and explicit product ownership.

Revision ID: b19e8a6c4f20
Revises: d8ac2ee32ec4
"""
from alembic import op
import sqlalchemy as sa

revision = "b19e8a6c4f20"
down_revision = "d8ac2ee32ec4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("products", sa.Column("owner_address", sa.String(42), nullable=True))
    op.add_column("products", sa.Column("ownership_source", sa.String(32), nullable=True))
    op.create_table(
        "auth_challenges",
        sa.Column("nonce_hash", sa.String(64), primary_key=True),
        sa.Column("address", sa.String(42), nullable=True),
        sa.Column("origin", sa.String(255), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message", sa.String(2048), nullable=True),
    )
    op.create_index("ix_auth_challenges_expires_at", "auth_challenges", ["expires_at"])


def downgrade():
    op.drop_index("ix_auth_challenges_expires_at", table_name="auth_challenges")
    op.drop_table("auth_challenges")
    op.drop_column("products", "ownership_source")
    op.drop_column("products", "owner_address")
