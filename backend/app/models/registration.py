"""Wallet submissions are claims; only checked chain evidence establishes success."""

from sqlalchemy import (
    Column,
    Integer,
    String,
    BigInteger,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    JSON,
)
from app.core.database import Base


class RegistrationAttempt(Base):
    __tablename__ = "registration_attempts"
    id = Column(Integer, primary_key=True)
    product_id = Column(
        String, ForeignKey("products.product_id"), nullable=False, index=True
    )
    chain_id = Column(BigInteger, nullable=False)
    registry_address = Column(String(42), nullable=False)
    submitted_by = Column(String(42), nullable=False)
    tx_hash = Column(String(66), nullable=False)
    operation = Column(String(16), nullable=False)
    registration_payload = Column(JSON, nullable=False, default=dict)
    metadata_uri = Column(String(500), nullable=True)
    status = Column(String(24), nullable=False, default="submitted")
    reason = Column(String(64), nullable=False, default="awaiting_receipt")
    nonce = Column(BigInteger, nullable=True)
    replaces_tx_hash = Column(String(66), nullable=True)
    replaced_by = Column(String(66), nullable=True)
    block_number = Column(BigInteger, nullable=True)
    block_hash = Column(String(66), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    checked_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint(
            "chain_id", "tx_hash", name="uq_registration_attempt_chain_tx"
        ),
        CheckConstraint(
            "operation IN ('registration','metadata')",
            name="ck_registration_attempt_operation",
        ),
        CheckConstraint(
            "status IN ('submitted','confirming','indexing','indexed','failed','replaced')",
            name="ck_registration_attempt_status",
        ),
    )
