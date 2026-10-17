from sqlalchemy import Column, Integer, String, DateTime, BigInteger
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
    registered_at = Column(DateTime, nullable=False)
    block_number = Column(BigInteger, nullable=False)
    tx_hash = Column(String, nullable=False)
