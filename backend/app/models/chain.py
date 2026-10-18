"""Durable indexing state. Journal occurrences retain orphaned history for audit."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    JSON,
    String,
    ForeignKey,
    Index,
)
from app.core.database import Base
from sqlalchemy.orm import relationship, backref


class IndexerCursor(Base):
    __tablename__ = "indexer_cursors"
    scope = Column(String(64), primary_key=True)
    chain_id = Column(BigInteger, nullable=False)
    registry_address = Column(String(42), nullable=False)
    tracker_address = Column(String(42), nullable=False)
    start_block = Column(BigInteger, nullable=False)
    last_processed_block = Column(BigInteger, nullable=False)
    block_hash = Column(String(66), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class ChainBlock(Base):
    __tablename__ = "chain_blocks"
    scope = Column(String(64), primary_key=True)
    number = Column(BigInteger, primary_key=True)
    block_hash = Column(String(66), nullable=False)


class ChainEvent(Base):
    __tablename__ = "chain_events"
    occurrence_id = Column(String(64), primary_key=True)
    scope = Column(String(64), nullable=False)
    event_id = Column(String(255), nullable=False, index=True)
    chain_id = Column(BigInteger, nullable=False)
    contract_address = Column(String(42), nullable=False)
    transaction_hash = Column(String(66), nullable=False)
    log_index = Column(Integer, nullable=False)
    transaction_index = Column(Integer, nullable=False)
    block_number = Column(BigInteger, nullable=False)
    block_hash = Column(String(66), nullable=False)
    event_type = Column(String(40), nullable=False)
    product_key = Column(String(66), nullable=False)
    payload = Column(JSON, nullable=False)
    canonical = Column(Boolean, nullable=False, default=True)
    processed_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        Index(
            "ix_chain_events_replay",
            "scope",
            "canonical",
            "block_number",
            "transaction_index",
            "log_index",
        ),
        Index("ix_chain_events_product", "scope", "product_key"),
        Index(
            "uq_chain_events_canonical_event",
            "event_id",
            unique=True,
            postgresql_where=canonical.is_(True),
            sqlite_where=canonical.is_(True),
        ),
    )


class IndexedProduct(Base):
    """Binding and pre-indexing draft snapshot; never guessed from product names."""

    __tablename__ = "indexed_products"
    scope = Column(String(64), primary_key=True)
    product_key = Column(String(66), primary_key=True)
    product_id = Column(
        String, ForeignKey("products.product_id"), nullable=False, unique=True
    )
    product = relationship("Product", backref=backref("indexed_state", uselist=False))
    baseline = Column(JSON, nullable=False)
    current_handler = Column(String(42), nullable=True)
    status = Column(String(50), nullable=False, default="0")
