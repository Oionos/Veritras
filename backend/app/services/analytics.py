from collections import defaultdict
from statistics import stdev
from typing import Optional, List, Dict
from sqlalchemy import func
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta

from app.models.product import Product
from app.models.shipment import Checkpoint, Shipment
from app.schemas.analytics import AnomalyResponse, DailyVolumeItem


def _compute_transit_times(db: Session) -> List[Dict[str, float | str]]:
    """Compute transit time per product in hours."""
    rows = (
        db.query(
            Checkpoint.product_id,
            func.min(Checkpoint.timestamp).label("first_seen"),
            func.max(Checkpoint.timestamp).label("last_seen"),
        )
        .group_by(Checkpoint.product_id)
        .all()
    )

    transit_times: List[Dict[str, float | str]] = []
    for product_id, first_seen, last_seen in rows:
        if first_seen is None or last_seen is None:
            continue
        transit_times.append(
            {
                "product_id": product_id,
                "transit_time_hours": (last_seen - first_seen).total_seconds() / 3600.0,
            }
        )
    return transit_times


def calculate_avg_transit_time(db: Session) -> Optional[float]:
    """
    Calculate the average transit time between the first and last checkpoint
    for each product, then return the overall average in hours.
    """
    transit_times = _compute_transit_times(db)
    if not transit_times:
        return None
    total_hours = sum(float(row["transit_time_hours"]) for row in transit_times)
    return total_hours / len(transit_times)


def detect_anomalies(db: Session, z_threshold: float = 2.0) -> List[AnomalyResponse]:
    """
    Detect anomalous transit times using Z-score analysis.
    """
    transit_times = _compute_transit_times(db)
    if len(transit_times) < 2:
        return []

    values = [float(row["transit_time_hours"]) for row in transit_times]
    mean_tt = sum(values) / len(values)
    std_tt = stdev(values)
    if std_tt == 0:
        return []

    anomalies = []
    now = datetime.now(timezone.utc).isoformat()
    for row in transit_times:
        transit_hours = float(row["transit_time_hours"])
        z_score = (transit_hours - mean_tt) / std_tt
        z = abs(z_score)
        if z <= z_threshold:
            continue
        if z > 3.0:
            severity = "high"
        elif z > 2.5:
            severity = "medium"
        else:
            severity = "low"
        anomalies.append(
            AnomalyResponse(
                product_id=str(row["product_id"]),
                transit_time_hours=transit_hours,
                z_score=z_score,
                severity=severity,
                flagged_at=now,
            )
        )
    return anomalies


def calculate_on_time_rate(
    db: Session, expected_hours: float = 72.0
) -> Optional[float]:
    """
    Calculate the percentage of shipments delivered within the expected duration.
    """
    transit_times = _compute_transit_times(db)
    if not transit_times:
        return None
    on_time = sum(
        1 for row in transit_times if float(row["transit_time_hours"]) <= expected_hours
    )
    total = len(transit_times)
    return float((on_time / total) * 100) if total > 0 else None


def get_bottleneck_locations(db: Session, min_dwell_hours: float = 24.0) -> List[Dict]:
    """
    Look at consecutive checkpoints for each product and compute dwell time
    at each location. Return locations where average dwell time exceeds threshold.
    """
    checkpoints = (
        db.query(Checkpoint.product_id, Checkpoint.location, Checkpoint.timestamp)
        .order_by(Checkpoint.product_id.asc(), Checkpoint.timestamp.asc())
        .all()
    )
    if not checkpoints:
        return []

    dwell_by_location: dict[str, list[float]] = defaultdict(list)
    previous = None
    for checkpoint in checkpoints:
        if previous is not None and previous.product_id == checkpoint.product_id:
            dwell_hours = (
                checkpoint.timestamp - previous.timestamp
            ).total_seconds() / 3600.0
            dwell_by_location[previous.location].append(dwell_hours)
        previous = checkpoint

    bottlenecks = []
    for location, dwell_hours in dwell_by_location.items():
        avg_dwell = sum(dwell_hours) / len(dwell_hours)
        if avg_dwell > min_dwell_hours:
            bottlenecks.append(
                {
                    "location": location,
                    "avg_dwell_hours": avg_dwell,
                    "incident_count": len(dwell_hours),
                }
            )

    return sorted(bottlenecks, key=lambda row: row["avg_dwell_hours"], reverse=True)


def get_kpi_summary(db: Session) -> Dict:
    """
    Aggregate all KPIs into a single response dict.
    """
    total_shipments = db.query(Shipment).count()
    if total_shipments:
        delivered_shipments = db.query(Shipment).filter(Shipment.status == "3").count()
        active_shipments = db.query(Shipment).filter(Shipment.status != "3").count()
    else:
        delivered_ids = (
            db.query(Checkpoint.product_id)
            .filter(Checkpoint.status == "3")
            .distinct()
            .subquery()
        )
        delivered_shipments = (
            db.query(Product)
            .filter(Product.registration_status != "superseded")
            .filter(Product.product_id.in_(delivered_ids.select()))
            .count()
        )

        products_with_checkpoints = (
            db.query(Checkpoint.product_id).distinct().subquery()
        )
        total_shipments = (
            db.query(Product)
            .filter(Product.registration_status != "superseded")
            .filter(Product.product_id.in_(products_with_checkpoints.select()))
            .count()
        )
        active_shipments = (
            db.query(Product)
            .filter(Product.registration_status != "superseded")
            .filter(Product.product_id.in_(products_with_checkpoints.select()))
            .filter(Product.product_id.notin_(delivered_ids.select()))
            .count()
        )

    avg_transit = calculate_avg_transit_time(db)
    on_time = calculate_on_time_rate(db)

    checkpoint_counts = db.query(Checkpoint).count()
    avg_checkpoints = (
        checkpoint_counts / total_shipments if total_shipments > 0 else 0.0
    )

    bottlenecks = get_bottleneck_locations(db)

    return {
        "avg_transit_time_hours": avg_transit,
        "on_time_rate_percent": on_time,
        "total_shipments": total_shipments,
        "active_shipments": active_shipments,
        "delivered_shipments": delivered_shipments,
        "avg_checkpoints_per_shipment": avg_checkpoints,
        "bottleneck_locations": bottlenecks,
    }


def get_daily_volume_data(db: Session) -> List[DailyVolumeItem]:
    """Query daily product registrations and shipment creations for the last 7 days."""
    today = datetime.utcnow().date()
    dates = [today - timedelta(days=i) for i in range(6, -1, -1)]
    start_dt = datetime.combine(dates[0], datetime.min.time())

    product_counts: dict[str, int] = {d.isoformat(): 0 for d in dates}
    shipment_counts: dict[str, int] = {d.isoformat(): 0 for d in dates}

    product_rows = (
        db.query(func.date(Product.created_at), func.count(Product.id))
        .filter(
            Product.created_at >= start_dt, Product.registration_status != "superseded"
        )
        .group_by(func.date(Product.created_at))
        .all()
    )
    shipment_rows = (
        db.query(func.date(Shipment.created_at), func.count(Shipment.id))
        .filter(Shipment.created_at >= start_dt)
        .group_by(func.date(Shipment.created_at))
        .all()
    )

    for day, count in product_rows:
        product_counts[day.isoformat() if hasattr(day, "isoformat") else str(day)] = (
            count
        )

    for day, count in shipment_rows:
        shipment_counts[day.isoformat() if hasattr(day, "isoformat") else str(day)] = (
            count
        )

    items: List[DailyVolumeItem] = []
    for d in dates:
        date_str = d.isoformat()
        items.append(
            DailyVolumeItem(
                name=d.strftime("%a"),
                date=date_str,
                shipments=shipment_counts.get(date_str, 0),
                products=product_counts.get(date_str, 0),
            )
        )
    return items
