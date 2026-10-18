import asyncio
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Literal, Optional, List

from app.core.database import get_db
from app.core.limiter import limiter
from app.services.analytics import get_kpi_summary, detect_anomalies, get_bottleneck_locations, get_daily_volume_data
from app.services.events import broadcaster, chain_revision
from app.services.export import export_to_csv, export_to_pdf
from app.schemas.analytics import KPIResponse, AnomalyResponse, DailyVolumeResponse

router = APIRouter()


@router.get("/kpis", response_model=KPIResponse)
@limiter.limit("10/minute")
def get_kpis(request: Request, db: Session = Depends(get_db)):
    """Return key performance indicators for the supply chain."""
    return get_kpi_summary(db)


@router.get("/anomalies", response_model=List[AnomalyResponse])
@limiter.limit("10/minute")
def get_anomalies(
    request: Request,
    z_threshold: float = Query(2.0, ge=0.5),
    db: Session = Depends(get_db)
):
    """Detect anomalous shipment transit times using Z-score analysis."""
    return detect_anomalies(db, z_threshold=z_threshold)


@router.get("/bottlenecks")
@limiter.limit("10/minute")
def get_bottlenecks(
    request: Request,
    min_dwell_hours: float = Query(24.0, ge=0.0),
    db: Session = Depends(get_db)
):
    """Identify bottleneck locations based on average dwell time between checkpoints."""
    return get_bottleneck_locations(db, min_dwell_hours=min_dwell_hours)


@router.get("/export")
@limiter.limit("10/minute")
def export_analytics(
    request: Request,
    format: Literal["csv", "pdf"] = Query("csv"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Export analytics data to CSV or PDF."""
    if format == "csv":
        content = export_to_csv(db, start_date, end_date)
        return StreamingResponse(
            iter([content]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=veritras_export.csv"},
        )
    else:
        content = export_to_pdf(db, start_date, end_date)
        return StreamingResponse(
            iter([content]),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=veritras_export.pdf"},
        )


@router.get("/daily-volume", response_model=DailyVolumeResponse)
@limiter.limit("10/minute")
def get_daily_volume(request: Request, db: Session = Depends(get_db)):
    """Return daily shipment and product registration counts for the last 7 days."""
    items = get_daily_volume_data(db)
    return {"items": items}


@router.get("/events")
async def analytics_events():
    """Server-Sent Events stream for real-time analytics updates."""
    queue = broadcaster.subscribe()

    async def event_generator():
        try:
            revision = await asyncio.to_thread(chain_revision)
            yield 'event: resync\ndata: {}\n\n'
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=5)
                    yield message
                except asyncio.TimeoutError:
                    yield ': heartbeat\n\n'
                latest = await asyncio.to_thread(chain_revision)
                if latest != revision:
                    revision = latest
                    yield 'event: chain_updated\ndata: {}\n\n'
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
