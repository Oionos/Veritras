from typing import Literal, Optional
from pydantic import BaseModel


class IndexerHealthResponse(BaseModel):
    status: Literal[
        "disabled",
        "not_started",
        "starting",
        "catching_up",
        "current",
        "degraded",
        "stopping",
        "stopped",
    ]
    enabled: bool = True
    ready: bool = False
    reason: Optional[str] = None
    phase: str = "not_started"
    last_processed_block: Optional[int] = None
    chain_head: Optional[int] = None
    target_head: Optional[int] = None
    lag_blocks: Optional[int] = None
    finality_gap_blocks: Optional[int] = None
    last_success_at: Optional[str] = None
    last_poll_at: Optional[str] = None
    last_progress_at: Optional[str] = None
    started_at: Optional[str] = None
    observed_head_at: Optional[str] = None
    head_changed_at: Optional[str] = None
    startup_age_seconds: Optional[float] = None
    success_age_seconds: Optional[float] = None
    progress_age_seconds: Optional[float] = None
    head_age_seconds: Optional[float] = None
    last_error: Optional[str] = None
    initialization_error: Optional[str] = None
    consecutive_failures: int = 0
    retry_delay_seconds: Optional[float] = None
    poll_interval_seconds: int
    startup_timeout_seconds: int
    stale_after_seconds: int
    head_stale_after_seconds: int
    max_lag_blocks: int
    chain_id: int
    confirmation_policy: Literal["depth"] = "depth"
    confirmations: int
    cursor_storage: Literal["database"] = "database"
    last_reorg_ancestor: Optional[int] = None
    recovery_reason: Optional[str] = None


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"
    environment: str
    chain_id: int
    release_commit: Optional[str] = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["connected", "disconnected", "timed_out"]
    environment: str
    chain_id: int
    release_commit: Optional[str] = None
    indexer: IndexerHealthResponse
