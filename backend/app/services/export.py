"""Exports use the exact same shipment creation cohort and evidence as KPIs."""

import csv
import re
from io import StringIO, BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import landscape, letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from app.services.analytics import (
    shipment_dataset,
    parse_filters,
    iso,
    _summary,
    sla_eligible,
    utc,
)

SHIPMENT_COLUMNS = [
    "shipment_id",
    "product_id",
    "origin",
    "destination",
    "notes",
    "created_at_utc",
    "expected_arrival_at_utc",
    "expected_arrival_recorded_at_utc",
    "departed_at_utc",
    "delivered_at_utc",
    "transit_time_hours",
    "delivered",
    "sla_eligible",
    "on_time",
    "checkpoint_count",
    "event_count",
    "evidence_event_ids",
    "evidence_tx_hashes",
    "chain_id",
    "registry_address",
    "tracker_address",
]
EVENT_COLUMNS = [
    "shipment_id",
    "product_id",
    "event_id",
    "event_type",
    "timestamp_utc",
    "location",
    "status",
    "notes",
    "handler_address",
    "from_address",
    "to_address",
    "metadata_uri",
    "product_name",
    "block_number",
    "block_hash",
    "tx_hash",
    "log_index",
    "chain_id",
    "contract_address",
]


def safe_csv(value):
    """Quote escaping alone does not stop spreadsheet formula execution.

    Prefix user text beginning (after whitespace/control characters) with any
    formula trigger. A literal leading apostrophe is harmless in spreadsheets.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        leading = re.sub(r"^[\s\x00-\x20\ufeff]*", "", value)
        if leading.startswith(("=", "+", "-", "@")) or value.startswith(
            ("\t", "\r", "\n")
        ):
            return "'" + value
    return value


def export_to_csv(
    db,
    start_date=None,
    end_date=None,
    origin=None,
    destination=None,
    report="shipments",
):
    records = shipment_dataset(
        db, parse_filters(start_date, end_date, origin, destination)
    )
    buffer = StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=EVENT_COLUMNS if report == "events" else SHIPMENT_COLUMNS
    )
    writer.writeheader()
    for r in records:
        s = r["shipment"]
        if report == "events":
            from datetime import datetime, timezone

            for e in r["events"]:
                timestamp = e.payload.get("timestamp")
                row = dict(
                    shipment_id=s.shipment_id,
                    product_id=s.product_id,
                    event_id=e.event_id,
                    event_type=e.event_type,
                    timestamp_utc=(
                        iso(datetime.fromtimestamp(int(timestamp), timezone.utc))
                        if timestamp is not None
                        else ""
                    ),
                    location=e.payload.get("location"),
                    status=e.payload.get("status"),
                    notes=e.payload.get("notes"),
                    handler_address=e.payload.get("handler"),
                    from_address=e.payload.get("from"),
                    to_address=e.payload.get("to"),
                    metadata_uri=e.payload.get("metadataURI"),
                    product_name=e.payload.get("name"),
                    block_number=e.block_number,
                    block_hash=e.block_hash,
                    tx_hash=e.transaction_hash,
                    log_index=e.log_index,
                    chain_id=e.chain_id,
                    contract_address=e.contract_address,
                )
                writer.writerow({k: safe_csv(v) for k, v in row.items()})
        else:
            row = dict(
                shipment_id=s.shipment_id,
                product_id=s.product_id,
                origin=s.origin,
                destination=s.destination,
                notes=s.notes,
                created_at_utc=iso(s.created_at),
                expected_arrival_at_utc=iso(s.expected_arrival_at),
                expected_arrival_recorded_at_utc=iso(s.expected_arrival_recorded_at),
                departed_at_utc=iso(r["departed_at"]),
                delivered_at_utc=iso(r["delivered_at"]),
                transit_time_hours=r["transit_time_hours"],
                delivered=bool(r["delivered_at"]),
                sla_eligible=sla_eligible(r),
                on_time=(
                    (r["delivered_at"] <= utc(s.expected_arrival_at))
                    if sla_eligible(r)
                    else None
                ),
                checkpoint_count=len(r["checkpoints"]),
                event_count=len(r["events"]),
                evidence_event_ids=";".join(e.event_id for e in r["events"]),
                evidence_tx_hashes=";".join(
                    dict.fromkeys(e.transaction_hash for e in r["events"])
                ),
                chain_id=s.product.chain_id,
                registry_address=s.product.registry_address,
                tracker_address=s.product.tracker_address,
            )
            writer.writerow({k: safe_csv(v) for k, v in row.items()})
    return buffer.getvalue()


def export_to_pdf(db, start_date=None, end_date=None, origin=None, destination=None):
    filters = parse_filters(start_date, end_date, origin, destination)
    records = shipment_dataset(db, filters)
    summary = _summary(records)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(letter), rightMargin=30, leftMargin=30
    )
    styles = getSampleStyleSheet()

    def paragraph(value, style="Normal"):
        return Paragraph(escape(str(value)), styles[style])

    story = [
        paragraph("Veritras Shipment Report", "Title"),
        Spacer(1, 12),
        paragraph(
            f"UTC shipment creation cohort: [{iso(filters.start) or 'unbounded'}, {iso(filters.end) or 'unbounded'})"
        ),
        paragraph(
            f"Route: {filters.origin or 'all origins'} to {filters.destination or 'all destinations'}"
        ),
        paragraph(
            f"Total Shipments: {summary['total_shipments']} | Delivered: {summary['delivered_shipments']} | Active: {summary['active_shipments']}"
        ),
        paragraph(
            f"Completed transit samples: {summary['transit_sample_size']} | SLA samples: {summary['sla_sample_size']} | Unknown SLA deliveries: {summary['unknown_sla_deliveries']}"
        ),
        paragraph(
            f"Late/unproven SLA deliveries excluded: {summary['late_sla_deliveries']} | Incomplete SLA deliveries excluded: {summary['incomplete_sla_deliveries']}"
        ),
        paragraph(
            "Departure/delivery require canonical indexed events. Blank SLA or transit means unknown. Checkpoint intervals are not dwell time."
        ),
        Spacer(1, 12),
    ]
    for r in records:
        s = r["shipment"]
        story.extend(
            [
                paragraph(f"{s.shipment_id} / {s.product_id}", "Heading2"),
                paragraph(f"Route: {s.origin} to {s.destination}"),
                paragraph(
                    f"Expected arrival UTC: {iso(s.expected_arrival_at) or 'Unknown'}"
                ),
                paragraph(
                    f"Departure UTC: {iso(r['departed_at']) or 'Unknown'} | Delivery UTC: {iso(r['delivered_at']) or 'Unknown'}"
                ),
                paragraph(
                    f"Canonical checkpoints: {len(r['checkpoints'])} | Canonical events: {len(r['events'])}"
                ),
            ]
        )
        for e in r["events"]:
            story.append(
                paragraph(
                    f"{e.event_type}: {e.event_id} | transaction {e.transaction_hash} log {e.log_index}, block {e.block_number} ({e.block_hash}), chain {e.chain_id}, contract {e.contract_address}"
                )
            )
        if not r["events"]:
            story.append(paragraph("No canonical evidence"))
        story.append(Spacer(1, 12))
    if not records:
        story.append(paragraph("No shipments in this cohort."))
    doc.build(story)
    return buffer.getvalue()
