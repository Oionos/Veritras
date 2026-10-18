from pydantic import BaseModel
from typing import Optional


class CheckpointInterval(BaseModel):
    location: str
    avg_interval_hours: float
    incident_count: int


class ShipmentMetrics(BaseModel):
    avg_transit_time_hours: Optional[float]
    on_time_rate_percent: Optional[float]
    total_shipments: int
    active_shipments: int
    delivered_shipments: int
    avg_checkpoints_per_shipment: float
    bottleneck_locations: list[CheckpointInterval]
    transit_sample_size: int
    incomplete_transit_shipments: int
    on_time_shipments: int
    sla_sample_size: int
    late_sla_deliveries: int
    incomplete_sla_deliveries: int
    unknown_sla_deliveries: int
    avg_active_elapsed_hours: Optional[float]
    active_elapsed_sample_size: int
    awaiting_departure_shipments: int
    checkpoint_count: int
    event_count: int


class RouteMetrics(ShipmentMetrics):
    origin: str
    destination: str


class AnalyticsFilters(BaseModel):
    start: Optional[str]
    end_exclusive: Optional[str]
    origin: Optional[str]
    destination: Optional[str]
    timezone: str
    cohort: str


class ShipmentTrend(BaseModel):
    current_count: int
    previous_count: int
    percent_change: Optional[float]
    previous_start: str
    previous_end_exclusive: str


class KPIResponse(ShipmentMetrics):
    routes: list[RouteMetrics]
    filters: AnalyticsFilters
    as_of: str
    anomaly_rule: str
    trend: Optional[ShipmentTrend]


class AnomalyResponse(BaseModel):
    product_id: str
    transit_time_hours: float
    z_score: float
    severity: str
    flagged_at: str
    origin: str = ""
    destination: str = ""
    sample_size: int = 0


class DailyVolumeItem(BaseModel):
    name: str
    date: str
    shipments: int
    products: int


class DailyVolumeResponse(BaseModel):
    items: list[DailyVolumeItem]
