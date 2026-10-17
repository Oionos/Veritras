from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import List, Optional, Literal
from datetime import datetime


class CheckpointBase(BaseModel):
    product_id: str = Field(..., max_length=100)
    location: str = Field(..., max_length=200)
    status: str = Field(..., max_length=50)
    handler_address: str = Field(..., max_length=100)
    notes: Optional[str] = Field(default=None, max_length=1000)
    timestamp: datetime
    block_number: int
    tx_hash: str = Field(..., max_length=100)


class CheckpointResponse(CheckpointBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class CustodyTransferBase(BaseModel):
    product_id: str = Field(..., max_length=100)
    from_address: str = Field(..., max_length=100)
    to_address: str = Field(..., max_length=100)
    timestamp: datetime
    block_number: int
    tx_hash: str = Field(..., max_length=100)


class CustodyTransferResponse(CustodyTransferBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class ShipmentBase(BaseModel):
    product_id: str = Field(..., max_length=100)
    origin: str = Field(..., max_length=200)
    destination: str = Field(..., max_length=200)
    status: str = Field(default="0", max_length=50)
    notes: Optional[str] = Field(default=None, max_length=1000)


class ShipmentCreate(ShipmentBase):
    status: Literal["0"] = "0"
    model_config = ConfigDict(extra='forbid')


class ShipmentUpdate(BaseModel):
    origin: Optional[str] = Field(default=None, max_length=200)
    destination: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=1000)

    model_config = ConfigDict(extra='forbid')

    @field_validator("origin", "destination")
    @classmethod
    def location_cannot_be_null(cls, value):
        if value is None or not value.strip():
            raise ValueError("Location must not be empty")
        return value


class ShipmentResponse(ShipmentBase):
    id: int
    shipment_id: str = Field(..., max_length=100)
    owner_address: Optional[str] = None
    ownership_source: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    block_number: int
    tx_hash: str = Field(..., max_length=100)

    model_config = ConfigDict(from_attributes=True, extra='forbid')


class ShipmentListResponse(BaseModel):
    items: List[ShipmentResponse]
    total: int
