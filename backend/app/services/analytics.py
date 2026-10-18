"""Shipment analytics. Dates select shipment creation cohorts, not event windows.

All lifecycle evidence comes from the canonical journal in one SQL snapshot.
A checkpoint interval is not dwell time. Missing departure/SLA stays unknown.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import mean, stdev
import re

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.models.chain import ChainEvent, IndexedProduct
from app.models.product import Product
from app.models.shipment import Shipment
from app.schemas.analytics import AnomalyResponse, DailyVolumeItem


def utc(value):
    if value is None:
        return None
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def iso(value):
    return utc(value).isoformat() if value else None


@dataclass(frozen=True)
class AnalyticsFilter:
    start: datetime | None = None
    end: datetime | None = None
    origin: str | None = None
    destination: str | None = None

    def metadata(self):
        return dict(
            start=iso(self.start),
            end_exclusive=iso(self.end),
            origin=self.origin,
            destination=self.destination,
            timezone="UTC",
            cohort="shipment_created_at",
        )


def parse_filters(start_date=None, end_date=None, origin=None, destination=None):
    try:
        if any(
            v and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", str(v))
            for v in (start_date, end_date)
        ):
            raise ValueError("Invalid calendar date")
        start = (
            datetime.combine(
                date.fromisoformat(str(start_date)), datetime.min.time(), timezone.utc
            )
            if start_date
            else None
        )
        end = (
            datetime.combine(
                date.fromisoformat(str(end_date)), datetime.min.time(), timezone.utc
            )
            + timedelta(days=1)
            if end_date
            else None
        )
    except (ValueError, OverflowError):
        raise HTTPException(
            422, "Dates must be ISO calendar dates (YYYY-MM-DD)"
        ) from None
    if start and end and start >= end:
        raise HTTPException(422, "start_date must be on or before end_date")
    if any(value is not None and not value.strip() for value in (origin, destination)):
        raise HTTPException(422, "Route locations must not be blank")
    return AnalyticsFilter(
        start,
        end,
        origin.strip().lower() if origin else None,
        destination.strip().lower() if destination else None,
    )


def shipment_query(db, filters):
    query = (
        db.query(Shipment)
        .options(joinedload(Shipment.product))
        .join(Product, Shipment.product_id == Product.product_id)
        .filter(Product.registration_status != "superseded")
    )
    if filters.start:
        query = query.filter(Shipment.created_at >= filters.start.replace(tzinfo=None))
    if filters.end:
        query = query.filter(Shipment.created_at < filters.end.replace(tzinfo=None))
    for column, value in (
        (Shipment.origin, filters.origin),
        (Shipment.destination, filters.destination),
    ):
        if value:
            query = query.filter(func.lower(func.trim(column)) == value)
    return query


def shipment_dataset(db: Session, filters=None, product_id=None, product_ids=None):
    """One statement for a consistent shipment + canonical evidence snapshot.

    Join through the identity binding, selected contract, chain and product key;
    a display ID, untagged legacy checkpoint or cached status is never proof.
    """
    query = shipment_query(db, filters or AnalyticsFilter())
    if product_id:
        query = query.filter(Shipment.product_id == product_id)
    if product_ids is not None:
        query = query.filter(Shipment.product_id.in_(product_ids))
    event_contract = or_(
        and_(
            ChainEvent.event_type.in_(["ProductRegistered", "ProductMetadataUpdated"]),
            func.lower(ChainEvent.contract_address)
            == func.lower(Product.registry_address),
        ),
        and_(
            ChainEvent.event_type.in_(
                ["CheckpointRecorded", "DeliveryCompleted", "CustodyTransferred"]
            ),
            func.lower(ChainEvent.contract_address)
            == func.lower(Product.tracker_address),
        ),
    )
    rows = (
        query.outerjoin(IndexedProduct, IndexedProduct.product_id == Product.product_id)
        .outerjoin(
            ChainEvent,
            and_(
                ChainEvent.scope == IndexedProduct.scope,
                ChainEvent.product_key == IndexedProduct.product_key,
                ChainEvent.product_key == Product.on_chain_product_id,
                ChainEvent.chain_id == Product.chain_id,
                ChainEvent.canonical.is_(True),
                event_contract,
            ),
        )
        .add_entity(ChainEvent)
        .order_by(
            Shipment.created_at.desc(),
            Shipment.id.desc(),
            ChainEvent.block_number,
            ChainEvent.transaction_index,
            ChainEvent.log_index,
        )
        .all()
    )
    records = {}
    for shipment, event in rows:
        record = records.setdefault(
            shipment.id,
            dict(
                shipment=shipment,
                events=[],
                checkpoints=[],
                departed_at=None,
                delivered_at=None,
            ),
        )
        if event is None:
            continue
        record["events"].append(event)
        try:
            timestamp = datetime.fromtimestamp(
                int(event.payload["timestamp"]), timezone.utc
            )
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        if event.event_type == "CheckpointRecorded":
            record["checkpoints"].append((event, timestamp))
            if (
                str(event.payload.get("status")) == "1"
                and record["departed_at"] is None
            ):
                record["departed_at"] = timestamp
        if event.event_type == "DeliveryCompleted" or (
            event.event_type == "CheckpointRecorded"
            and str(event.payload.get("status")) == "3"
        ):
            if record["delivered_at"] is None:
                record["delivered_at"] = timestamp
    for record in records.values():
        departure, delivery = record["departed_at"], record["delivered_at"]
        record["transit_time_hours"] = (
            (delivery - departure).total_seconds() / 3600
            if departure and delivery and delivery >= departure
            else None
        )
    return list(records.values())


def hydrate_lifecycle(db, shipments):
    # A list route uses a bounded page; one shared query avoids per-row journal reads.
    identities = {s.product_id: s for s in shipments}
    if not identities:
        return
    # Reuse the same evidence definition. Restrict the statement to the page IDs.
    for record in shipment_dataset(db, product_ids=list(identities)):
        shipment = identities.get(record["shipment"].product_id)
        if shipment:
            shipment.departed_at = record["departed_at"]
            shipment.delivered_at = record["delivered_at"]


def _completed(records):
    return [r for r in records if r["transit_time_hours"] is not None]


def _average(values):
    values = list(values)
    return mean(values) if values else None


def calculate_avg_transit_time(db):
    return _average(r["transit_time_hours"] for r in _completed(shipment_dataset(db)))


def calculate_on_time_rate(db):
    return _summary(shipment_dataset(db))["on_time_rate_percent"]


def _intervals(records, minimum=24):
    groups = defaultdict(list)
    for record in records:
        checkpoints = record["checkpoints"]
        for (previous, start), (_, end) in zip(checkpoints, checkpoints[1:]):
            if end >= start:
                groups[
                    str(previous.payload.get("location", "")).strip().lower()
                ].append((end - start).total_seconds() / 3600)
    return [
        dict(
            location=location,
            avg_interval_hours=mean(values),
            incident_count=len(values),
        )
        for location, values in sorted(groups.items())
        if mean(values) > minimum
    ]


def get_bottleneck_locations(db, min_dwell_hours=24.0, filters=None):
    """Compatibility URL: these are checkpoint intervals, never dwell claims."""
    return _intervals(shipment_dataset(db, filters), min_dwell_hours)


def sla_eligible(record):
    shipment = record["shipment"]
    return bool(
        record["transit_time_hours"] is not None
        and shipment.expected_arrival_at
        and shipment.expected_arrival_recorded_at
        and utc(shipment.expected_arrival_recorded_at) <= record["departed_at"]
    )


def _summary(records, now=None):
    now = now or datetime.now(timezone.utc)
    delivered = [r for r in records if r["delivered_at"]]
    completed = _completed(records)
    eligible = [r for r in completed if sla_eligible(r)]
    late_sla = sum(
        bool(r["shipment"].expected_arrival_at)
        and (
            not r["shipment"].expected_arrival_recorded_at
            or utc(r["shipment"].expected_arrival_recorded_at) > r["departed_at"]
        )
        for r in completed
    )
    on_time = sum(
        r["delivered_at"] <= utc(r["shipment"].expected_arrival_at) for r in eligible
    )
    active_elapsed = [
        (now - r["departed_at"]).total_seconds() / 3600
        for r in records
        if r["departed_at"] and not r["delivered_at"] and r["departed_at"] <= now
    ]
    return dict(
        total_shipments=len(records),
        active_shipments=len(records) - len(delivered),
        delivered_shipments=len(delivered),
        avg_transit_time_hours=_average(r["transit_time_hours"] for r in completed),
        transit_sample_size=len(completed),
        incomplete_transit_shipments=len(records) - len(completed),
        on_time_rate_percent=100 * on_time / len(eligible) if eligible else None,
        on_time_shipments=on_time,
        late_sla_deliveries=late_sla,
        sla_sample_size=len(eligible),
        unknown_sla_deliveries=sum(
            not r["shipment"].expected_arrival_at for r in delivered
        ),
        incomplete_sla_deliveries=sum(
            bool(r["shipment"].expected_arrival_at) and r["transit_time_hours"] is None
            for r in delivered
        ),
        avg_active_elapsed_hours=_average(active_elapsed),
        active_elapsed_sample_size=len(active_elapsed),
        awaiting_departure_shipments=sum(
            not r["departed_at"] and not r["delivered_at"] for r in records
        ),
        avg_checkpoints_per_shipment=(
            sum(len(r["checkpoints"]) for r in records) / len(records)
            if records
            else 0.0
        ),
        checkpoint_count=sum(len(r["checkpoints"]) for r in records),
        event_count=sum(len(r["events"]) for r in records),
        bottleneck_locations=_intervals(records),
    )


def get_kpi_summary(db, filters=None):
    filters = filters or AnalyticsFilter()
    records = shipment_dataset(db, filters)
    result = _summary(records)
    groups = defaultdict(list)
    for r in records:
        s = r["shipment"]
        groups[(s.origin.strip().lower(), s.destination.strip().lower())].append(r)
    result["routes"] = [
        dict(origin=o, destination=d, **_summary(items))
        for (o, d), items in sorted(groups.items())
    ]
    result["filters"] = filters.metadata()
    result["as_of"] = datetime.now(timezone.utc).isoformat()
    result["anomaly_rule"] = (
        "Two-sided sample Z-score > 2 within the same normalized route; at least 10 completed journeys per route. Zero variance and smaller cohorts are suppressed."
    )
    result["trend"] = None
    # A comparison requires two explicit, equally sized, bounded creation periods.
    if (
        filters.start
        and filters.end
        and filters.start.toordinal() > (filters.end - filters.start).days
    ):
        previous = AnalyticsFilter(
            filters.start - (filters.end - filters.start),
            filters.start,
            filters.origin,
            filters.destination,
        )
        prior = shipment_query(db, previous).count()
        result["trend"] = dict(
            current_count=len(records),
            previous_count=prior,
            percent_change=100 * (len(records) - prior) / prior if prior else None,
            previous_start=iso(previous.start),
            previous_end_exclusive=iso(previous.end),
        )
    return result


def detect_anomalies(db, z_threshold=2.0, filters=None):
    groups = defaultdict(list)
    for r in _completed(shipment_dataset(db, filters)):
        s = r["shipment"]
        groups[(s.origin.strip().lower(), s.destination.strip().lower())].append(r)
    results = []
    for (origin, destination), records in groups.items():
        if len(records) < 10:
            continue
        values = [r["transit_time_hours"] for r in records]
        deviation = stdev(values)
        if not deviation:
            continue
        for r in records:
            score = (r["transit_time_hours"] - mean(values)) / deviation
            if abs(score) > z_threshold:
                results.append(
                    AnomalyResponse(
                        product_id=r["shipment"].product_id,
                        transit_time_hours=r["transit_time_hours"],
                        z_score=score,
                        severity=(
                            "high"
                            if abs(score) > 3
                            else "medium" if abs(score) > 2.5 else "low"
                        ),
                        flagged_at=datetime.now(timezone.utc).isoformat(),
                        origin=origin,
                        destination=destination,
                        sample_size=len(records),
                    )
                )
    return results


def get_daily_volume_data(db, filters=None):
    """Last seven UTC creation days. Products means drafts created, not registrations.

    Date/route filters apply to the shipment series; the product series is a
    separately labelled creation metric and is hidden for route filters.
    """
    filters = filters or AnalyticsFilter()
    today = datetime.now(timezone.utc).date()
    dates = [today - timedelta(days=i) for i in range(6, -1, -1)]
    counts = defaultdict(int)
    for record in shipment_dataset(db, filters):
        counts[utc(record["shipment"].created_at).date()] += 1
    query = db.query(func.date(Product.created_at), func.count(Product.id)).filter(
        Product.registration_status != "superseded",
        Product.created_at >= datetime.combine(dates[0], datetime.min.time()),
    )
    if filters.start:
        query = query.filter(Product.created_at >= filters.start.replace(tzinfo=None))
    if filters.end:
        query = query.filter(Product.created_at < filters.end.replace(tzinfo=None))
    products = (
        {
            str(day): count
            for day, count in query.group_by(func.date(Product.created_at)).all()
        }
        if not (filters.origin or filters.destination)
        else {}
    )
    return [
        DailyVolumeItem(
            name=d.strftime("%a"),
            date=d.isoformat(),
            shipments=counts[d],
            products=products.get(d.isoformat(), 0),
        )
        for d in dates
    ]
