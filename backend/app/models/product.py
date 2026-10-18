from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    BigInteger,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
)
from app.core.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(String, index=True, nullable=False, unique=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    metadata_uri = Column(String, nullable=True)
    manufacturer_address = Column(String, nullable=False)
    # NULL ownership on existing records is deliberate: legacy manufacturer
    # values were supplied by anonymous clients and grant no edit rights.
    owner_address = Column(String(42), nullable=True)
    ownership_source = Column(String(32), nullable=True)
    on_chain_product_id = Column(String(66), nullable=True)
    chain_id = Column(BigInteger, nullable=True)
    registry_address = Column(String(42), nullable=True)
    tracker_address = Column(String(42), nullable=True)
    registration_status = Column(
        String(32),
        nullable=False,
        default="legacy_unreconciled",
        server_default="legacy_unreconciled",
    )
    created_at = Column(DateTime, nullable=True)
    chain_registered_at = Column(DateTime, nullable=True)
    # Compatibility timestamp for old deployed readers; new responses expose
    # chain_registered_at as registered_at. Never use this field as proof.
    registered_at = Column(DateTime, nullable=False)
    block_number = Column(BigInteger, nullable=False)
    tx_hash = Column(String, nullable=False)

    @property
    def has_shipment(self):
        return bool(self.shipments)

    __table_args__ = (
        UniqueConstraint(
            "chain_id",
            "registry_address",
            "on_chain_product_id",
            name="uq_products_canonical_identity",
        ),
        CheckConstraint(
            "registration_status IN ('draft','indexed','unregistered','legacy_unreconciled','superseded')",
            name="ck_products_registration_status",
        ),
        CheckConstraint(
            "(on_chain_product_id IS NULL AND chain_id IS NULL AND registry_address IS NULL AND tracker_address IS NULL) OR (on_chain_product_id IS NOT NULL AND chain_id IS NOT NULL AND chain_id > 0 AND registry_address IS NOT NULL AND tracker_address IS NOT NULL AND length(on_chain_product_id)=66 AND lower(on_chain_product_id)=on_chain_product_id AND length(registry_address)=42 AND lower(registry_address)=registry_address AND length(tracker_address)=42 AND lower(tracker_address)=tracker_address)",
            name="ck_products_identity_scope",
        ),
    )


class ProductAlias(Base):
    __tablename__ = "product_aliases"
    alias_id = Column(String, primary_key=True)
    product_id = Column(
        String, ForeignKey("products.product_id"), nullable=False, index=True
    )
    __table_args__ = (
        CheckConstraint("alias_id != product_id", name="ck_product_alias_not_self"),
    )
