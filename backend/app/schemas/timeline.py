from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel


class TimelineEvent(BaseModel):
    event_id: str
    event_type: Literal[
        "ProductRegistered",
        "ProductMetadataUpdated",
        "CheckpointRecorded",
        "CustodyTransferred",
        "DeliveryCompleted",
    ]
    timestamp: Optional[datetime] = None
    block_number: int
    block_hash: str
    transaction_hash: str
    transaction_index: int
    log_index: int
    contract_address: str
    location: Optional[str] = None
    status: Optional[str] = None
    handler: Optional[str] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    notes: Optional[str] = None
    metadata_uri: Optional[str] = None


class TimelineResponse(BaseModel):
    product_id: str
    chain_id: Optional[int] = None
    items: list[TimelineEvent]
    total: int
    skip: int
    limit: int
