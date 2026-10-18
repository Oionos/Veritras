import logging
import os
import re
import logging.config
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from web3 import Web3

from app.core.config import settings
from app.core.database import engine, Base
from app.core.limiter import limiter
from app.core.logging import LOGGING_CONFIG
from app.core.security import SecurityHeadersMiddleware
from app.api.routes import auth, products, shipments, analytics
from app.services.indexer import EventIndexer
from app.services.health import DatabaseProbe
from app.schemas.health import (
    IndexerHealthResponse,
    LivenessResponse,
    ReadinessResponse,
)

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("veritras.api")

w3: Optional[Web3] = None
indexer: Optional[EventIndexer] = None
_indexer_startup_error = None


def release_commit():
    value = os.environ.get("RENDER_GIT_COMMIT", "")
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


def _probe_database():
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.exec_driver_sql("SET LOCAL statement_timeout = '1000ms'")
        conn.execute(text("SELECT 1"))


_database_probe = DatabaseProbe(_probe_database)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.is_hosted:
        Base.metadata.create_all(bind=engine)

    global indexer, _indexer_startup_error
    indexer = None
    owned_indexer = None
    _indexer_startup_error = None
    if settings.indexer_enabled:
        try:
            owned_indexer = EventIndexer()
            owned_indexer.start()
            indexer = owned_indexer
            logger.info("Blockchain indexer startup scheduled")
        except Exception as error:
            _indexer_startup_error = type(error).__name__
            # Exception messages may include authenticated RPC endpoints.
            logger.error("Indexer thread startup failed: %s", _indexer_startup_error)
    else:
        logger.info("Blockchain indexing explicitly disabled")
    try:
        yield
    finally:
        if owned_indexer is not None:
            owned_indexer.stop()
            logger.info("Blockchain indexer shutdown requested")
        indexer = None


app = FastAPI(title="Veritras API", version="0.1.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


def parse_cors_origins(cors_origins: str) -> list[str]:
    origins = [
        origin.strip().rstrip("/")
        for origin in cors_origins.split(",")
        if origin.strip()
    ]
    if "*" in origins and len(origins) > 1:
        logger.warning(
            "Wildcard '*' mixed with explicit origins; treating as allow-all"
        )
    logger.info("Parsed CORS origins: %s", origins)
    return origins


cors_raw = settings.effective_cors_origins
logger.info("CORS config — raw value: %r", cors_raw)

origins = parse_cors_origins(cors_raw)
has_wildcard = "*" in origins

if settings.is_hosted and (not origins or has_wildcard):
    raise RuntimeError(
        "CORS_ORIGINS must be set to explicit origins in production. "
        "Wildcard '*' is not allowed with credentials enabled."
    )

allow_credentials = not has_wildcard

if allow_credentials and has_wildcard:
    logger.warning(
        "CORS allow_credentials=True is used with wildcard origin '*'. This is a security risk."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=600,
)

app.add_middleware(SecurityHeadersMiddleware)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    if request.url.path == "/health" or request.url.path.startswith("/health/"):
        response.headers["Cache-Control"] = "no-store"
    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "client_ip": request.client.host if request.client else None,
        },
    )
    return response


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(products.router, prefix="/products", tags=["products"])
app.include_router(shipments.router, prefix="/shipments", tags=["shipments"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])


def indexer_state():
    if settings.indexer_enabled and indexer is not None:
        return IndexerHealthResponse.model_validate(indexer.health())
    return IndexerHealthResponse(
        status="not_started" if settings.indexer_enabled else "disabled",
        enabled=settings.indexer_enabled,
        reason=(
            "thread_start_failed"
            if _indexer_startup_error
            else (
                "worker_not_started"
                if settings.indexer_enabled
                else "indexing_disabled"
            )
        ),
        initialization_error=(
            _indexer_startup_error if settings.indexer_enabled else None
        ),
        last_error=_indexer_startup_error if settings.indexer_enabled else None,
        chain_id=settings.chain_id,
        confirmations=settings.indexer_confirmations,
        poll_interval_seconds=settings.indexer_poll_interval,
        startup_timeout_seconds=settings.indexer_startup_timeout,
        stale_after_seconds=max(
            settings.indexer_stale_after, settings.indexer_poll_interval * 3
        ),
        head_stale_after_seconds=(
            settings.indexer_head_stale_after if settings.chain_id != 31337 else 0
        ),
        max_lag_blocks=settings.indexer_max_lag_blocks,
    )


@app.get(
    "/health/indexer",
    response_model=IndexerHealthResponse,
    responses={503: {"model": IndexerHealthResponse}},
)
async def health_indexer():
    """Cached worker health; a progressing backfill is healthy but not ready."""
    state = indexer_state()
    healthy = state.status in {"current", "catching_up", "disabled"}
    return JSONResponse(status_code=200 if healthy else 503, content=state.model_dump())


@app.get("/health/live", response_model=LivenessResponse)
async def health_live():
    # No database/RPC work: backfill and dependency outages must not restart APIs.
    return LivenessResponse(
        environment=settings.environment,
        chain_id=settings.chain_id,
        release_commit=release_commit(),
    )


def readiness_state():
    database = _database_probe.status(settings.health_database_timeout)
    state = indexer_state()
    ready = database == "connected" and (not settings.indexer_enabled or state.ready)
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        database=database,
        environment=settings.environment,
        chain_id=settings.chain_id,
        release_commit=release_commit(),
        indexer=state,
    )


@app.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def health_ready():
    state = readiness_state()
    return JSONResponse(
        status_code=200 if state.status == "ready" else 503, content=state.model_dump()
    )


@app.get("/health")
def health_check():
    """Compatibility summary of readiness. Does not make a separate RPC call."""
    state = readiness_state()
    ready = state.status == "ready"
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ok" if ready else "degraded",
            "database": state.database,
            "web3": (
                "not_required"
                if not settings.indexer_enabled
                else (
                    "connected" if state.indexer.status == "current" else "disconnected"
                )
            ),
        },
    )


@app.get("/health/cors")
def health_cors():
    """Expose currently configured CORS origins for production debugging."""
    return {
        "cors_origins_raw": settings.effective_cors_origins,
        "cors_origins_parsed": origins,
        "allow_credentials": allow_credentials,
        "environment": settings.environment,
    }
