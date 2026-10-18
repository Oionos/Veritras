from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, Literal
from datetime import datetime


class ProductBase(BaseModel):
    name: str = Field(..., max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    metadata_uri: Optional[str] = Field(default=None, max_length=500)


class ProductCreate(ProductBase):
    # Accepted for older clients only; the signed-in wallet is authoritative.
    manufacturer_address: Optional[str] = Field(default=None, pattern=r"^0x[a-fA-F0-9]{40}$")
    model_config = ConfigDict(extra='forbid')


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    metadata_uri: Optional[str] = Field(default=None, max_length=500)

    model_config = ConfigDict(extra='forbid')

    @field_validator("name")
    @classmethod
    def name_cannot_be_null(cls, value):
        if value is None or not value.strip():
            raise ValueError("Name must not be empty")
        return value


class ProductResponse(ProductBase):
    id: int
    product_id: str = Field(..., max_length=100)
    manufacturer_address: str = Field(..., max_length=42)
    owner_address: Optional[str] = None
    ownership_source: Optional[str] = None
    registered_at: datetime
    block_number: int
    tx_hash: str = Field(..., max_length=100)

    model_config = ConfigDict(from_attributes=True, extra='forbid')


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    total: int


class SynchronizationResponse(BaseModel):
    confirmation_policy: Literal['depth'] = 'depth'
    confirmations: int
    cursor_storage: Literal['database'] = 'database'
    indexer_enabled: bool
    indexed_block: Optional[int] = None
    last_successful_sync: Optional[datetime] = None


class VerificationResponse(BaseModel):
    product_id: str
    is_registered: bool
    is_delivered: bool
    checkpoint_count: int
    synchronization: SynchronizationResponse
