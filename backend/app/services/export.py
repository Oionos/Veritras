from typing import Optional
from io import StringIO, BytesIO
from sqlalchemy.orm import Session
from datetime import datetime

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from app.models.product import Product
from app.models.shipment import Checkpoint, CustodyTransfer


def export_to_csv(
    db: Session, start_date: Optional[str], end_date: Optional[str]
) -> str:
    """
    Query products and checkpoints within date range and export to CSV.
    Returns CSV content as a string.
    """
    query = db.query(Product).filter(Product.registration_status != "superseded")
    if start_date:
        query = query.filter(
            Product.registered_at >= datetime.fromisoformat(start_date)
        )
    if end_date:
        query = query.filter(Product.registered_at <= datetime.fromisoformat(end_date))
    products = query.all()

    if not products:
        return ""

    product_ids = [p.product_id for p in products]
    checkpoints = (
        db.query(Checkpoint)
        .filter(Checkpoint.product_id.in_(product_ids))
        .order_by(Checkpoint.product_id, Checkpoint.timestamp)
        .all()
    )

    rows = []
    for cp in checkpoints:
        rows.append(
            {
                "product_id": cp.product_id,
                "location": cp.location,
                "status": cp.status,
                "handler_address": cp.handler_address,
                "notes": cp.notes,
                "timestamp": cp.timestamp.isoformat() if cp.timestamp else "",
                "block_number": cp.block_number,
                "tx_hash": cp.tx_hash,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return ""

    buffer = StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue()


def export_to_pdf(
    db: Session, start_date: Optional[str], end_date: Optional[str]
) -> bytes:
    """
    Generate a simple PDF report with summary stats and a table of shipments.
    Returns PDF content as bytes.
    """
    query = db.query(Product).filter(Product.registration_status != "superseded")
    if start_date:
        query = query.filter(
            Product.registered_at >= datetime.fromisoformat(start_date)
        )
    if end_date:
        query = query.filter(Product.registered_at <= datetime.fromisoformat(end_date))
    products = query.all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # Title
    story.append(Paragraph("<b>Veritras Supply Chain Report</b>", styles["Title"]))
    story.append(Spacer(1, 12))

    # Date range
    range_text = f"Date Range: {start_date or 'All time'} to {end_date or 'All time'}"
    story.append(Paragraph(range_text, styles["Normal"]))
    story.append(Spacer(1, 12))

    # Summary stats
    total_products = len(products)
    product_ids = [p.product_id for p in products]
    checkpoint_count = (
        db.query(Checkpoint).filter(Checkpoint.product_id.in_(product_ids)).count()
    )
    transfer_count = (
        db.query(CustodyTransfer)
        .filter(CustodyTransfer.product_id.in_(product_ids))
        .count()
    )

    summary_data = [
        ["Metric", "Value"],
        ["Total Shipments", str(total_products)],
        ["Total Checkpoints", str(checkpoint_count)],
        ["Total Custody Transfers", str(transfer_count)],
    ]
    summary_table = Table(summary_data, hAlign="LEFT")
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 24))

    # Shipment table
    if products:
        story.append(Paragraph("<b>Shipments</b>", styles["Heading2"]))
        story.append(Spacer(1, 12))
        shipment_data = [["Product ID", "Name", "Manufacturer", "Registered At"]]
        for p in products:
            shipment_data.append(
                [
                    p.product_id,
                    p.name,
                    p.manufacturer_address,
                    p.registered_at.isoformat() if p.registered_at else "",
                ]
            )
        shipment_table = Table(shipment_data, hAlign="LEFT")
        shipment_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
        )
        story.append(shipment_table)

    doc.build(story)
    buffer.seek(0)
    return buffer.read()
