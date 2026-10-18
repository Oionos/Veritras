"""Cached worker observations. Health requests never call an RPC provider."""

import logging
import threading
import time
from datetime import datetime, timezone
from app.core.config import settings

logger = logging.getLogger("veritras.indexer")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class IndexerHealth:
    def _init_health(self):
        self._health_lock = threading.RLock()
        self.last_error = self.initialization_error = None
        self.last_success_at = self.last_poll_at = self.last_progress_at = None
        self.started_at = self.observed_head_at = self.head_changed_at = None
        self._last_success_monotonic = self._last_poll_monotonic = None
        self._last_progress_monotonic = self._started_monotonic = None
        self._head_changed_monotonic = self._observed_head = None
        self.last_processed_block = self.chain_head = self.target_head = None
        self.last_reorg_ancestor = self.recovery_reason = None
        self.phase = "not_started"
        self.consecutive_failures = 0
        self.retry_delay_seconds = None
        self._logged_state = None

    def _observe_head(self, head):
        now, timestamp = time.monotonic(), utc_now()
        with self._health_lock:
            if self._observed_head != head:
                self._head_changed_monotonic = now
                self.head_changed_at = timestamp
                self._observed_head = head
            self.observed_head_at = timestamp
            self.chain_head = head
            self.target_head = max(0, head - settings.indexer_confirmations)

    def _record_success(self, previous):
        now, timestamp = time.monotonic(), utc_now()
        with self._health_lock:
            self.last_success_at = self.last_poll_at = timestamp
            self._last_success_monotonic = self._last_poll_monotonic = now
            if (
                self.last_processed_block != previous
                or self._last_progress_monotonic is None
            ):
                self.last_progress_at = timestamp
                self._last_progress_monotonic = now
            self.last_error = self.initialization_error = self.recovery_reason = None
            self.consecutive_failures = 0
            self.retry_delay_seconds = None
            self.phase = "waiting"

    def health(self):
        now = time.monotonic()
        with self._health_lock:

            def age(value):
                return None if value is None else max(0.0, now - value)

            success_age = age(self._last_success_monotonic)
            progress_age = age(self._last_progress_monotonic)
            startup_age = age(self._started_monotonic)
            head_age = age(self._head_changed_monotonic)
            stale_after = max(settings.indexer_stale_after, self.poll_interval * 3)
            # Hardhat deliberately mines only on demand; idle is normal there.
            head_stale_after = (
                settings.indexer_head_stale_after if settings.chain_id != 31337 else 0
            )
            lag = (
                None
                if self.target_head is None or self.last_processed_block is None
                else max(0, self.target_head - self.last_processed_block)
            )
            gap = (
                None
                if self.target_head is None or self.last_processed_block is None
                else max(0, self.last_processed_block - self.target_head)
            )
            thread_dead = self._thread is not None and not self._thread.is_alive()
            if not self.running or thread_dead:
                status, reason = "stopped", "worker_stopped"
            elif self._stop_event.is_set():
                status, reason = "stopping", "shutdown_requested"
            elif self.last_error:
                status, reason = "degraded", self.recovery_reason or "poll_failed"
            elif success_age is None:
                status, reason = (
                    ("degraded", "startup_timeout")
                    if startup_age is not None
                    and startup_age >= settings.indexer_startup_timeout
                    else ("starting", "initializing")
                )
            elif success_age >= stale_after:
                status, reason = "degraded", "poll_stale"
            elif lag is None or gap is None:
                status, reason = "degraded", "cursor_unavailable"
            elif (
                head_stale_after
                and head_age is not None
                and head_age >= head_stale_after
            ):
                status, reason = "degraded", "chain_head_stalled"
            elif gap:
                status, reason = "catching_up", "awaiting_confirmation_depth"
            elif lag > settings.indexer_max_lag_blocks:
                status, reason = (
                    ("degraded", "progress_stalled")
                    if progress_age is not None and progress_age >= stale_after
                    else ("catching_up", "backfill")
                )
            else:
                status, reason = "current", None
            return dict(
                status=status,
                reason=reason,
                phase=self.phase,
                enabled=True,
                ready=status == "current",
                last_processed_block=self.last_processed_block,
                chain_head=self.chain_head,
                target_head=self.target_head,
                lag_blocks=lag,
                finality_gap_blocks=gap,
                last_success_at=self.last_success_at,
                last_poll_at=self.last_poll_at,
                last_progress_at=self.last_progress_at,
                started_at=self.started_at,
                observed_head_at=self.observed_head_at,
                head_changed_at=self.head_changed_at,
                startup_age_seconds=startup_age,
                success_age_seconds=success_age,
                progress_age_seconds=progress_age,
                head_age_seconds=head_age,
                last_error=self.last_error,
                initialization_error=self.initialization_error,
                consecutive_failures=self.consecutive_failures,
                retry_delay_seconds=self.retry_delay_seconds,
                poll_interval_seconds=self.poll_interval,
                startup_timeout_seconds=settings.indexer_startup_timeout,
                stale_after_seconds=stale_after,
                head_stale_after_seconds=head_stale_after,
                max_lag_blocks=settings.indexer_max_lag_blocks,
                chain_id=settings.chain_id,
                confirmation_policy="depth",
                confirmations=settings.indexer_confirmations,
                cursor_storage="database",
                last_reorg_ancestor=self.last_reorg_ancestor,
                recovery_reason=self.recovery_reason,
            )

    def _log_health_transition(self):
        state = self.health()
        signature = state["status"], state["reason"]
        if self._logged_state != signature:
            self._logged_state = signature
            logger.log(
                (
                    logging.WARNING
                    if state["status"] in {"degraded", "stopped"}
                    else logging.INFO
                ),
                "indexer_state_changed",
                extra={
                    key: state[key]
                    for key in (
                        "status",
                        "reason",
                        "last_processed_block",
                        "target_head",
                        "lag_blocks",
                        "last_error",
                    )
                },
            )
