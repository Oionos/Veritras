"""Off-chain operational observations, separate from canonical chain evidence."""

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    CheckConstraint,
    BigInteger,
)
from app.core.database import Base
from sqlalchemy.orm import relationship


class ExceptionPolicy(Base):
    __tablename__ = "exception_policies"
    shipment_id = Column(String, ForeignKey("shipments.shipment_id"), primary_key=True)
    revision = Column(Integer, nullable=False)
    arrival_enabled = Column(Boolean, nullable=False)
    inactivity_hours = Column(Float, nullable=True)
    checkpoint_hours = Column(Float, nullable=True)
    custody_hours = Column(Float, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    updated_by = Column(String(42), nullable=False)
    __table_args__ = tuple(
        CheckConstraint(
            f"{name} IS NULL OR ({name} >= 0.25 AND {name} <= 8760)",
            name=f"ck_exception_policy_{name}",
        )
        for name in ("inactivity_hours", "checkpoint_hours", "custody_hours")
    )


class ShipmentException(Base):
    __tablename__ = "shipment_exceptions"
    id = Column(String(36), primary_key=True)
    scope = Column(String(64), nullable=False)
    shipment_id = Column(String, ForeignKey("shipments.shipment_id"), nullable=False)
    kind = Column(String(32), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    triggered_at = Column(DateTime(timezone=True), nullable=False)
    first_observed_at = Column(DateTime(timezone=True), nullable=False)
    last_observed_at = Column(DateTime(timezone=True), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution = Column(String(40), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(String(42), nullable=True)
    acknowledgement_note = Column(String(500), nullable=True)
    evidence = Column(JSON, nullable=False)
    shipment = relationship("Shipment")

    @property
    def owner_address(self):
        return self.shipment.product.owner_address

    @property
    def ownership_source(self):
        return self.shipment.product.ownership_source

    __table_args__ = (
        Index(
            "uq_shipment_exception_open",
            "scope",
            "shipment_id",
            "kind",
            unique=True,
            postgresql_where=resolved_at.is_(None),
            sqlite_where=resolved_at.is_(None),
        ),
        Index(
            "ix_shipment_exception_list", "scope", "resolved_at", "first_observed_at"
        ),
        CheckConstraint(
            "kind IN ('arrival_overdue','checkpoint_inactivity','checkpoint_wait','custody_followup')",
            name="ck_shipment_exception_kind",
        ),
    )


class ExceptionEvaluation(Base):
    __tablename__ = "exception_evaluations"
    scope = Column(String(64), primary_key=True)
    evaluated_at = Column(DateTime(timezone=True), nullable=False)
    block_number = Column(BigInteger, nullable=False)
    block_hash = Column(String(66), nullable=False)
    uncertain_shipments = Column(Integer, nullable=False, default=0)
