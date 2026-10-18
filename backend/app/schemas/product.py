from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, Literal
from datetime import datetime


class ProductBase(BaseModel):
    name: str = Field(..., max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    metadata_uri: Optional[str] = Field(default=None, max_length=500)


class ProductCreate(ProductBase):
    # Accepted for older clients only; the signed-in wallet is authoritative.
    manufacturer_address: Optional[str] = Field(
        default=None, pattern=r"^0x[a-fA-F0-9]{40}$"
    )
    model_config = ConfigDict(extra="forbid")


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    metadata_uri: Optional[str] = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")

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
    on_chain_product_id: Optional[str] = None
    chain_id: Optional[int] = None
    registry_address: Optional[str] = None
    tracker_address: Optional[str] = None
    registration_status: Literal[
        "draft", "indexed", "unregistered", "legacy_unreconciled", "superseded"
    ] = "legacy_unreconciled"
    has_shipment: bool = False
    created_at: Optional[datetime] = None
    registered_at: Optional[datetime] = Field(
        default=None, validation_alias="chain_registered_at"
    )
    block_number: int
    tx_hash: str = Field(..., max_length=100)

    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True, extra="forbid"
    )


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    total: int


class SynchronizationResponse(BaseModel):
    status: str = "unknown"
    reason: Optional[str] = None
    lag_blocks: Optional[int] = None
    confirmation_policy: Literal["depth"] = "depth"
    confirmations: int
    cursor_storage: Literal["database"] = "database"
    indexer_enabled: bool
    indexed_block: Optional[int] = None
    last_successful_sync: Optional[datetime] = None


class VerificationResponse(BaseModel):
    product_id: str
    is_registered: bool
    is_delivered: bool
    checkpoint_count: int
    synchronization: SynchronizationResponse
    evidence: "RegistrationEvidence"


class RegistrationSubmission(BaseModel):
    tx_hash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
    operation: Literal["registration", "metadata"] = "registration"
    metadata_uri: Optional[str] = Field(default=None, max_length=500)
    replaces_tx_hash: Optional[str] = Field(
        default=None, pattern=r"^0x[0-9a-fA-F]{64}$"
    )
    model_config = ConfigDict(extra="forbid")


class RegistrationAttemptResponse(BaseModel):
    tx_hash: str
    operation: Literal["registration", "metadata"]
    metadata_uri: Optional[str]
    status: Literal[
        "submitted", "confirming", "indexing", "indexed", "failed", "replaced"
    ]
    reason: str
    replaces_tx_hash: Optional[str]
    replaced_by: Optional[str]
    block_number: Optional[int]
    block_hash: Optional[str]
    created_at: datetime
    checked_at: Optional[datetime]
    model_config = ConfigDict(from_attributes=True)


class RegistrationLifecycleResponse(BaseModel):
    product_id: str
    attempts: list[RegistrationAttemptResponse]


class RegistrationEvidence(BaseModel):
    status: Literal[
        "verified", "pending", "unavailable", "not_found", "mismatched", "failed"
    ]
    reason: str
    registration_status: Literal[
        "draft",
        "submitted",
        "confirming",
        "indexing",
        "indexed",
        "failed",
        "replaced",
        "unregistered",
        "legacy_unreconciled",
        "superseded",
    ]
    chain_id: Optional[int] = None
    registry_address: Optional[str] = None
    on_chain_product_id: Optional[str] = None
    manufacturer_address: str
    transaction_hash: Optional[str] = None
    block_number: Optional[int] = None
    block_hash: Optional[str] = None
    confirmation_policy: Literal["depth"] = "depth"
    required_confirmations: int
    observed_confirmations: Optional[int] = None
    physical_authenticity_verified: Literal[False] = False


class MetadataVersionResponse(BaseModel):
    transaction_hash: str
    block_number: int
    block_hash: str
    log_index: int
    metadata_uri: Optional[str]
    canonical: bool


class MetadataHistoryResponse(BaseModel):
    product_id: str
    items: list[MetadataVersionResponse]


VerificationResponse.model_rebuild()
