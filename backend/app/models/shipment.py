from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, BigInteger, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(String, ForeignKey("products.product_id"), nullable=False, index=True)
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
    product_id = Column(String, ForeignKey("products.product_id"), nullable=False, index=True)
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
    product_id = Column(String, ForeignKey("products.product_id"), nullable=False, index=True)
    origin = Column(String, nullable=False)
    destination = Column(String, nullable=False)
    status = Column(String, nullable=False, default="0")
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    block_number = Column(BigInteger, nullable=False, default=0)
    tx_hash = Column(String, nullable=False, default="0x")

    product = relationship("Product", backref="shipments")

    @property
    def owner_address(self):
        return self.product.owner_address if self.product else None

    @property
    def ownership_source(self):
        return self.product.ownership_source if self.product else None
