from datetime import datetime
from pydantic import BaseModel, Field


class NonceResponse(BaseModel):
    nonce: str
    domain: str
    uri: str
    chain_id: int
    issued_at: datetime
    expires_at: datetime


class ChallengeRequest(BaseModel):
    address: str = Field(pattern=r"^0x[a-fA-F0-9]{40}$")


class ChallengeResponse(NonceResponse):
    message: str


class VerifyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2048)
    signature: str = Field(min_length=1, max_length=2048)


class VerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    address: str
