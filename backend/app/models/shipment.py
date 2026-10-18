from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    BigInteger,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        String, ForeignKey("products.product_id"), nullable=False, index=True
    )
    location = Column(String, nullable=False)
    status = Column(String, nullable=False)
    handler_address = Column(String, nullable=False)
    notes = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=False)
    block_number = Column(BigInteger, nullable=False)
    tx_hash = Column(String, nullable=False)
    source_event_id = Column(String(255), nullable=True, unique=True, index=True)

    product = relationship("Product", backref="checkpoints")


class CustodyTransfer(Base):
    __tablename__ = "custody_transfers"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(
        String, ForeignKey("products.product_id"), nullable=False, index=True
    )
    from_address = Column(String, nullable=False)
    to_address = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    block_number = Column(BigInteger, nullable=False)
    tx_hash = Column(String, nullable=False)
    source_event_id = Column(String(255), nullable=True, unique=True, index=True)

    product = relationship("Product", backref="custody_transfers")


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(String, index=True, nullable=False, unique=True)
    product_id = Column(
        String, ForeignKey("products.product_id"), nullable=False, index=True
    )
    origin = Column(String, nullable=False)
    destination = Column(String, nullable=False)
    status = Column(String, nullable=False, default="0")
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    block_number = Column(BigInteger, nullable=False, default=0)
    tx_hash = Column(String, nullable=False, default="0x")

    __table_args__ = (UniqueConstraint("product_id", name="uq_shipments_product_id"),)

    product = relationship("Product", backref="shipments")

    @property
    def owner_address(self):
        return self.product.owner_address if self.product else None

    @property
    def ownership_source(self):
        return self.product.ownership_source if self.product else None

    @property
    def current_handler(self):
        state = self.product.indexed_state if self.product else None
        return state.current_handler if state else None

    @property
    def on_chain_product_id(self):
        return self.product.on_chain_product_id if self.product else None

    @property
    def registry_address(self):
        return self.product.registry_address if self.product else None

    @property
    def chain_id(self):
        return self.product.chain_id if self.product else None

    @property
    def tracker_address(self):
        return self.product.tracker_address if self.product else None
