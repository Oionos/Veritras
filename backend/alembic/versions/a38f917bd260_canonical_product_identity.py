"""Canonical product scope, lifecycle and one shipment per item.

Revision ID: a38f917bd260
Revises: f04d9c21a873

Only existing canonical journal bindings establish migrated chain identity.
Unbound legacy values never grant ownership or manufacture registration proof.
"""

from datetime import datetime, timezone
import re
from alembic import op
import sqlalchemy as sa

revision = "a38f917bd260"
down_revision = "f04d9c21a873"
branch_labels = None
depends_on = None

SCOPE_CHECK = "(on_chain_product_id IS NULL AND chain_id IS NULL AND registry_address IS NULL AND tracker_address IS NULL) OR (on_chain_product_id IS NOT NULL AND chain_id IS NOT NULL AND chain_id > 0 AND registry_address IS NOT NULL AND tracker_address IS NOT NULL AND length(on_chain_product_id)=66 AND lower(on_chain_product_id)=on_chain_product_id AND length(registry_address)=42 AND lower(registry_address)=registry_address AND length(tracker_address)=42 AND lower(tracker_address)=tracker_address)"
STATUS_CHECK = "registration_status IN ('draft','indexed','unregistered','legacy_unreconciled','superseded')"


def _canonical(value):
    # Frozen conversion for this migration; do not depend on future app helpers.
    if value.lower().startswith("0x"):
        if not re.fullmatch(r"0[xX][0-9a-fA-F]{64}", value):
            raise RuntimeError("Invalid bound hexadecimal product identity")
        raw = bytes.fromhex(value[2:])
    else:
        raw = value.encode("utf-8")
        if not raw or len(raw) > 32 or b"\x00" in raw:
            raise RuntimeError("Invalid bound display product identity")
        raw = raw.ljust(32, b"\x00")
    if raw == bytes(32):
        raise RuntimeError("Invalid zero product identity")
    return "0x" + raw.hex()


def seed_bindings(connection):
    metadata = sa.MetaData()
    products = sa.Table("products", metadata, autoload_with=connection)
    bindings = sa.Table("indexed_products", metadata, autoload_with=connection)
    cursors = sa.Table("indexer_cursors", metadata, autoload_with=connection)
    events = sa.Table("chain_events", metadata, autoload_with=connection)
    for product in connection.execute(sa.select(products)).mappings().all():
        if (
            product["block_number"] == 0
            and product["ownership_source"] == "signed_draft"
        ):
            connection.execute(
                products.update()
                .where(products.c.id == product["id"])
                .values(
                    created_at=product["registered_at"], registration_status="draft"
                )
            )
    for binding in connection.execute(sa.select(bindings)).mappings().all():
        cursor = (
            connection.execute(
                sa.select(cursors).where(cursors.c.scope == binding["scope"])
            )
            .mappings()
            .one_or_none()
        )
        product = (
            connection.execute(
                sa.select(products).where(
                    products.c.product_id == binding["product_id"]
                )
            )
            .mappings()
            .one()
        )
        if (
            cursor is None
            or _canonical(product["product_id"]) != binding["product_key"]
        ):
            raise RuntimeError(
                "Projection binding requires identity reconciliation before migration"
            )
        values = dict(
            on_chain_product_id=binding["product_key"],
            chain_id=cursor["chain_id"],
            registry_address=cursor["registry_address"].lower(),
            tracker_address=cursor["tracker_address"].lower(),
        )
        registrations = (
            connection.execute(
                sa.select(events).where(
                    events.c.scope == binding["scope"],
                    events.c.product_key == binding["product_key"],
                    events.c.canonical.is_(True),
                    events.c.event_type == "ProductRegistered",
                )
            )
            .mappings()
            .all()
        )
        if len(registrations) > 1:
            raise RuntimeError(
                "Several canonical registrations require explicit reconciliation"
            )
        if registrations:
            event = registrations[0]
            args = event["payload"]
            if (
                product["block_number"] != event["block_number"]
                or product["tx_hash"].lower() != event["transaction_hash"]
                or product["manufacturer_address"].lower()
                != args["manufacturer"].lower()
                or product["name"] != args["name"]
                or product["ownership_source"] != "chain_event"
                or product["owner_address"] != args["manufacturer"].lower()
            ):
                raise RuntimeError(
                    "Product projection disagrees with its canonical registration"
                )
            values.update(
                registration_status="indexed",
                chain_registered_at=datetime.fromtimestamp(
                    args["timestamp"], timezone.utc
                ),
            )
        elif product["block_number"] != 0:
            raise RuntimeError(
                "Product claims registration without a canonical registration log"
            )
        connection.execute(
            products.update().where(products.c.id == product["id"]).values(**values)
        )
        baseline = dict(binding["baseline"])
        baseline.update(
            chain_registered_at=None,
            registration_status=(
                "draft"
                if baseline.get("ownership_source") == "signed_draft"
                else "legacy_unreconciled"
            ),
        )
        connection.execute(
            bindings.update()
            .where(
                bindings.c.scope == binding["scope"],
                bindings.c.product_key == binding["product_key"],
            )
            .values(baseline=baseline)
        )


def upgrade():
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text(
            "SELECT product_id FROM shipments GROUP BY product_id HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicates:
        raise RuntimeError(
            "Duplicate shipment lifecycles require review before canonical identity migration; no records were removed"
        )
    for name, kind in [
        ("on_chain_product_id", sa.String(66)),
        ("chain_id", sa.BigInteger()),
        ("registry_address", sa.String(42)),
        ("tracker_address", sa.String(42)),
        ("created_at", sa.DateTime()),
        ("chain_registered_at", sa.DateTime()),
    ]:
        op.add_column("products", sa.Column(name, kind, nullable=True))
    op.add_column(
        "products",
        sa.Column(
            "registration_status",
            sa.String(32),
            server_default="legacy_unreconciled",
            nullable=False,
        ),
    )
    seed_bindings(connection)
    with op.batch_alter_table("products") as batch:
        batch.create_unique_constraint(
            "uq_products_canonical_identity",
            ["chain_id", "registry_address", "on_chain_product_id"],
        )
        batch.create_check_constraint("ck_products_registration_status", STATUS_CHECK)
        batch.create_check_constraint("ck_products_identity_scope", SCOPE_CHECK)
    with op.batch_alter_table("shipments") as batch:
        batch.create_unique_constraint("uq_shipments_product_id", ["product_id"])
    op.create_table(
        "product_aliases",
        sa.Column("alias_id", sa.String(), primary_key=True),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey("products.product_id"),
            nullable=False,
        ),
        sa.CheckConstraint("alias_id != product_id", name="ck_product_alias_not_self"),
    )
    op.create_index("ix_product_aliases_product_id", "product_aliases", ["product_id"])


def downgrade():
    raise RuntimeError(
        "Canonical reconciliation preserves legacy aliases; use a reviewed corrective migration, not an automatic downgrade"
    )
