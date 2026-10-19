from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.health import ReadinessResponse


class BrowserMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Literal[
        "LCP",
        "CLS",
        "interaction_max_ms",
        "client_error",
        "api_error",
        "stream_disconnected",
        "stream_recovered",
    ]
    route: Literal[
        "dashboard",
        "products",
        "shipments",
        "shipment_detail",
        "analytics",
        "exceptions",
        "verify",
        "demo",
        "privacy",
        "terms",
        "not_found",
    ]
    value: float = Field(ge=0, le=600000, allow_inf_nan=False)
    release: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    environment: Literal["development", "testing", "production"]


class BrowserAggregate(BaseModel):
    metric: str
    route: str
    count: int
    mean: float


class OperationalCounters(BaseModel):
    window_seconds: int
    uptime_seconds: int
    requests: int
    api_requests: int
    api_5xx: int
    mean_duration_ms: float | None
    duration_buckets: dict[str, int]
    streams: dict[str, int]
    browser_metrics: list[BrowserAggregate]
    storage: Literal["process_memory"]
    reset_on_restart: bool


class OperationsResponse(BaseModel):
    health: ReadinessResponse
    counters: OperationalCounters
