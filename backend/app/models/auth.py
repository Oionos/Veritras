from sqlalchemy import Column, DateTime, Integer, String

from app.core.database import Base


class AuthChallenge(Base):
    __tablename__ = "auth_challenges"

    nonce_hash = Column(String(64), primary_key=True)
    address = Column(String(42), nullable=True)
    origin = Column(String(255), nullable=False)
    chain_id = Column(Integer, nullable=False)
    issued_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    message = Column(String(2048), nullable=True)
