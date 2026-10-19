import asyncio
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Literal, Optional, List

from app.core.database import get_db
from app.core.limiter import limiter
from app.services.analytics import (
    get_kpi_summary,
    detect_anomalies,
    get_bottleneck_locations,
    get_daily_volume_data,
    parse_filters,
)
from app.services.events import broadcaster, chain_revision
from app.services.export import export_to_csv, export_to_pdf
from app.schemas.analytics import (
    KPIResponse,
    AnomalyResponse,
    DailyVolumeResponse,
    CheckpointInterval,
)

router = APIRouter()


def analytics_filters(
    start_date: Optional[str] = Query(None, max_length=10),
    end_date: Optional[str] = Query(None, max_length=10),
    origin: Optional[str] = Query(None, min_length=1, max_length=200),
    destination: Optional[str] = Query(None, min_length=1, max_length=200),
):
    """UTC shipment creation dates [start, day after end); exact trimmed case-insensitive routes."""
    return parse_filters(start_date, end_date, origin, destination)


@router.get("/kpis", response_model=KPIResponse)
@limiter.limit("10/minute")
def get_kpis(
    request: Request, db: Session = Depends(get_db), filters=Depends(analytics_filters)
):
    """Return key performance indicators for the supply chain."""
    return get_kpi_summary(db, filters)


@router.get("/anomalies", response_model=List[AnomalyResponse])
@limiter.limit("10/minute")
def get_anomalies(
    request: Request,
    z_threshold: float = Query(2.0, ge=0.5),
    db: Session = Depends(get_db),
    filters=Depends(analytics_filters),
):
    """Detect anomalous shipment transit times using Z-score analysis."""
    return detect_anomalies(db, z_threshold=z_threshold, filters=filters)


@router.get("/bottlenecks", response_model=List[CheckpointInterval])
@limiter.limit("10/minute")
def get_bottlenecks(
    request: Request,
    min_dwell_hours: float = Query(24.0, ge=0.0),
    db: Session = Depends(get_db),
    filters=Depends(analytics_filters),
):
    """Compatibility URL: return canonical checkpoint intervals, not dwell times."""
    return get_bottleneck_locations(
        db, min_dwell_hours=min_dwell_hours, filters=filters
    )


@router.get("/export")
@limiter.limit("10/minute")
def export_analytics(
    request: Request,
    format: Literal["csv", "pdf"] = Query("csv"),
    report: Literal["shipments", "events"] = Query("shipments"),
    db: Session = Depends(get_db),
    filters=Depends(analytics_filters),
):
    """Export analytics data to CSV or PDF."""
    args = (
        db,
        filters.start.date().isoformat() if filters.start else None,
        (filters.end.date() - timedelta(days=1)).isoformat() if filters.end else None,
        filters.origin,
        filters.destination,
    )
    if format == "csv":
        content = export_to_csv(*args, report=report)
        return StreamingResponse(
            iter([content]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=veritras_export.csv"},
        )
    else:
        content = export_to_pdf(*args)
        return StreamingResponse(
            iter([content]),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=veritras_export.pdf"},
        )


@router.get("/daily-volume", response_model=DailyVolumeResponse)
@limiter.limit("10/minute")
def get_daily_volume(
    request: Request, db: Session = Depends(get_db), filters=Depends(analytics_filters)
):
    """Return daily shipment and product registration counts for the last 7 days."""
    items = get_daily_volume_data(db, filters)
    return {"items": items}


@router.get("/events")
async def analytics_events():
    """Server-Sent Events stream for real-time analytics updates."""
    queue = broadcaster.subscribe()

    async def event_generator():
        from app.services.operations import operations
        import logging

        try:
            revision = await asyncio.to_thread(chain_revision)
            operations.stream("resyncs")
            yield "event: resync\ndata: {}\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=5)
                    yield message
                except asyncio.TimeoutError:
                    yield ": heartbeat\nevent: heartbeat\ndata: {}\n\n"
                latest = await asyncio.to_thread(chain_revision)
                if latest != revision:
                    revision = latest
                    yield "event: chain_updated\ndata: {}\n\n"
        except asyncio.CancelledError:
            raise
        except Exception as error:
            operations.stream("failures")
            logging.getLogger("veritras.events").error(
                "event_stream_unavailable", extra={"error_type": type(error).__name__}
            )
            yield "event: unavailable\ndata: {}\n\n"
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
