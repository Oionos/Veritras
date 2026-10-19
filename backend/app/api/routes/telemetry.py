from fastapi import APIRouter, HTTPException, Request, Response
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.operations import BrowserMetric
from app.services.operations import operations

router = APIRouter()


@router.post("/browser", status_code=204)
@limiter.limit("60/minute")
def browser_metric(request: Request, metric: BrowserMetric):
    if metric.environment != settings.environment:
        raise HTTPException(422, "Telemetry environment does not match this API")
    operations.browser_metric(metric.metric, metric.route, metric.value)
    return Response(status_code=204)
