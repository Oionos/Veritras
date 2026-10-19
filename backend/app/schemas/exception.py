from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

ExceptionKind = Literal[
    "arrival_overdue", "checkpoint_inactivity", "checkpoint_wait", "custody_followup"
]


class PolicyValues(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arrival_enabled: bool = True
    inactivity_hours: float | None = Field(
        default=24.0, ge=0.25, le=8760, allow_inf_nan=False
    )
    checkpoint_hours: float | None = Field(
        default=24.0, ge=0.25, le=8760, allow_inf_nan=False
    )
    custody_hours: float | None = Field(
        default=6.0, ge=0.25, le=8760, allow_inf_nan=False
    )


class PolicyUpdate(PolicyValues):
    expected_revision: int = Field(ge=0)


class PolicyResponse(PolicyValues):
    model_config = ConfigDict(from_attributes=True)
    revision: int = 0
    updated_at: datetime | None = None
    updated_by: str | None = None


class Acknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=500)


class ExceptionEvidence(BaseModel):
    product_id: str
    anchor_event_id: str
    anchor_occurrence_id: str
    threshold_hours: float | None
    location: str | None = None
    receiving_handler: str | None = None
    policy_revision: int


class ExceptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    shipment_id: str
    kind: ExceptionKind
    owner_address: str | None
    ownership_source: str | None
    triggered_at: datetime
    first_observed_at: datetime
    last_observed_at: datetime
    resolved_at: datetime | None
    resolution: str | None
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    acknowledgement_note: str | None
    evidence: ExceptionEvidence


class EvaluationStatus(BaseModel):
    paused: bool
    reason: str | None
    evaluated_at: datetime | None
    block_number: int | None
    uncertain_shipments: int = 0


class ExceptionList(BaseModel):
    items: list[ExceptionResponse]
    total: int
    evaluation: EvaluationStatus
