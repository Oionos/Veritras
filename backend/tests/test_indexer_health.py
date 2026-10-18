import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from app.core.config import settings, Settings
from app.services.indexer import EventIndexer, IndexerStopping, ReconciliationRequired
from app.services.health import DatabaseProbe
from tests.test_indexer import stack, counts
import app.main as api


@pytest.fixture
def worker(monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(
        "app.services.indexer_health.time", SimpleNamespace(monotonic=lambda: clock.now)
    )
    for key, value in [
        ("indexer_stale_after", 120),
        ("indexer_startup_timeout", 60),
        ("indexer_head_stale_after", 300),
        ("indexer_max_lag_blocks", 0),
        ("chain_id", 11155111),
    ]:
        monkeypatch.setattr(settings, key, value)
    w = EventIndexer(rpc_url="https://private.invalid/token", poll_interval=15)
    w.running = True
    w._thread = SimpleNamespace(is_alive=lambda: True)
    w._started_monotonic = 950
    w._last_success_monotonic = w._last_progress_monotonic = 999
    w._head_changed_monotonic = 990
    w.chain_head, w.target_head, w.last_processed_block = 112, 100, 100
    w.last_success_at = "2026-10-18T00:00:00+00:00"
    return w, clock


def test_current_uses_confirmation_target_not_unconfirmed_head(worker):
    w, _ = worker
    state = w.health()
    assert state["ready"] and state["status"] == "current" and state["lag_blocks"] == 0
    assert (
        state["chain_head"] == 112
        and state["target_head"] == 100
        and state["confirmations"] == 12
    )


@pytest.mark.parametrize(
    "field,seconds,reason",
    [
        ("_last_success_monotonic", 121, "poll_stale"),
        ("_head_changed_monotonic", 301, "chain_head_stalled"),
    ],
)
def test_stale_observations_cannot_stay_ready(worker, field, seconds, reason):
    w, clock = worker
    setattr(w, field, clock.now - seconds)
    assert w.health()["status"] == "degraded" and w.health()["reason"] == reason
    assert not w.health()["ready"]


def test_initial_startup_is_bounded_even_if_no_rpc_returns(worker):
    w, clock = worker
    w._last_success_monotonic = None
    assert w.health()["status"] == "starting"
    clock.now += 10
    assert w.health()["reason"] == "startup_timeout" and not w.health()["ready"]


def test_backfill_requires_real_cursor_progress(worker):
    w, clock = worker
    w.last_processed_block = 10
    assert w.health()["status"] == "catching_up"
    w._last_success_monotonic = clock.now
    w._last_progress_monotonic = clock.now - 121
    assert w.health()["reason"] == "progress_stalled"
    assert not w.health()["ready"]


def test_old_policy_cursor_waits_for_new_confirmation_depth(worker):
    w, _ = worker
    w.last_processed_block = 101
    assert w.health()["status"] == "catching_up"
    assert w.health()["reason"] == "awaiting_confirmation_depth"
    assert w.health()["finality_gap_blocks"] == 1 and not w.health()["ready"]


def test_configured_lag_tolerance_is_explicit(worker, monkeypatch):
    w, _ = worker
    w.last_processed_block = 98
    assert not w.health()["ready"]
    monkeypatch.setattr(settings, "indexer_max_lag_blocks", 2)
    assert w.health()["ready"] and w.health()["max_lag_blocks"] == 2


def test_idle_hardhat_is_healthy(worker, monkeypatch):
    w, clock = worker
    w._head_changed_monotonic = clock.now - 10000
    monkeypatch.setattr(settings, "chain_id", 31337)
    assert w.health()["ready"] and w.health()["head_stale_after_seconds"] == 0


def test_head_poll_does_not_reset_head_change_or_progress(worker):
    w, clock = worker
    w._observe_head(112)
    first = w._head_changed_monotonic
    clock.now += 10
    w._observe_head(112)
    assert w._head_changed_monotonic == first
    w._record_success(100)
    assert w._last_progress_monotonic == 999
    w.last_processed_block = 101
    w._record_success(100)
    assert w._last_progress_monotonic == clock.now


@pytest.mark.parametrize(
    "status", ["current", "catching_up", "degraded", "starting", "stopped"]
)
def test_liveness_readiness_and_worker_health_have_distinct_meaning(
    client_fixture, worker, monkeypatch, status
):
    w, _ = worker
    if status == "catching_up":
        w.last_processed_block = 90
    if status == "degraded":
        w.last_error = "ConnectionError"
    if status == "starting":
        w._last_success_monotonic = None
    if status == "stopped":
        w.running = False
    monkeypatch.setattr(settings, "indexer_enabled", True)
    monkeypatch.setattr(api, "indexer", w)
    assert client_fixture.get("/health/live").status_code == 200
    result = client_fixture.get("/health/ready")
    assert result.status_code == (200 if status == "current" else 503)
    assert result.json()["indexer"]["status"] == status
    assert client_fixture.get("/health/indexer").status_code == (
        200 if status in {"current", "catching_up"} else 503
    )


def test_disabled_is_consistent_and_never_calls_rpc(client_fixture, monkeypatch):
    monkeypatch.setattr(settings, "indexer_enabled", False)
    unsafe = MagicMock()
    monkeypatch.setattr(api, "indexer", unsafe)
    for path in ("/health", "/health/live", "/health/ready", "/health/indexer"):
        assert client_fixture.get(path).status_code == 200
    unsafe.health.assert_not_called()
    assert client_fixture.get("/health/indexer").json()["status"] == "disabled"


def test_liveness_has_no_dependency_work_and_release_is_validated(
    client_fixture, monkeypatch
):
    probe = MagicMock()
    monkeypatch.setattr(api, "_database_probe", probe)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "https://private.invalid/token")
    assert client_fixture.get("/health/live").json()["release_commit"] is None
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    assert client_fixture.get("/health/live").json()["release_commit"] == "a" * 40
    probe.status.assert_not_called()


def test_database_probe_is_bounded_single_flight_and_recovers():
    gate, entered = threading.Event(), threading.Event()
    calls = []

    def check():
        calls.append(True)
        entered.set()
        gate.wait(2)

    probe = DatabaseProbe(check)
    try:
        assert probe.status(0.01) == "timed_out"
        assert entered.wait(1)
        assert probe.status(0.01) == "timed_out" and len(calls) == 1
        gate.set()
        assert probe._pending.result(timeout=1) == "connected"
        assert probe.status(1) == "connected"
    finally:
        gate.set()


def test_database_probe_failure_redacts_details():
    def check():
        raise ConnectionError("postgresql://private:password@secret.invalid/db")

    assert DatabaseProbe(check).status(1) == "disconnected"


def test_readiness_database_timeout_is_not_liveness_failure(
    client_fixture, monkeypatch
):
    monkeypatch.setattr(
        api, "_database_probe", SimpleNamespace(status=lambda _: "timed_out")
    )
    assert client_fixture.get("/health/ready").status_code == 503
    assert client_fixture.get("/health/live").status_code == 200


def test_initial_thread_failure_is_visible_and_secret_safe(
    db_session, monkeypatch, caplog
):
    monkeypatch.setattr(settings, "indexer_enabled", True)

    def fail():
        raise RuntimeError("https://private.invalid/secret")

    monkeypatch.setattr(api, "EventIndexer", fail)
    with TestClient(api.app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        state = response.json()["indexer"]
        assert (
            state["initialization_error"] == "RuntimeError"
            and state["reason"] == "thread_start_failed"
        )
        assert "secret" not in response.text
    assert "private.invalid" not in caplog.text


def test_retry_backoff_caps_resets_and_redacts(monkeypatch, caplog):
    w = EventIndexer()
    w.running = True
    attempts, delays = [], []

    def connect():
        attempts.append(True)
        if len(attempts) < 5:
            raise ConnectionError("https://private.invalid/token")
        w.product_registry = object()

    def poll():
        w.last_processed_block = w.chain_head = w.target_head = 1

    def wait(delay):
        delays.append(delay)
        if len(attempts) >= 5:
            w._stop_event.set()

    monkeypatch.setattr(settings, "indexer_retry_interval", 2)
    monkeypatch.setattr(settings, "indexer_retry_max_interval", 5)
    monkeypatch.setattr(w, "_connect", connect)
    monkeypatch.setattr(w, "poll_once", poll)
    monkeypatch.setattr(w._stop_event, "wait", wait)
    w._run()
    assert delays[:4] == [2, 4, 5, 5]
    assert w.consecutive_failures == 0 and w.initialization_error is None
    assert w.last_error is None and "private.invalid" not in caplog.text


def test_reconciliation_error_never_echoes_exception_text(monkeypatch, caplog):
    w = EventIndexer()
    w.running = True
    w.product_registry = object()

    def fail():
        raise ReconciliationRequired("https://private.invalid/token")

    monkeypatch.setattr(w, "poll_once", fail)
    monkeypatch.setattr(w._stop_event, "wait", lambda _: w._stop_event.set())
    w._run()
    assert w.recovery_reason == "reconciliation_required"
    assert "private.invalid" not in json.dumps(w.health()) + caplog.text


def test_start_cannot_overlap_a_stopping_thread():
    w = EventIndexer()
    w._thread = SimpleNamespace(is_alive=lambda: True)
    w._stop_event.set()
    with pytest.raises(RuntimeError, match="still stopping"):
        w.start()


def test_stop_does_not_claim_a_live_thread_is_stopped():
    w = EventIndexer()
    w.running = True
    w._thread = SimpleNamespace(is_alive=lambda: True, join=lambda **_: None)
    assert w.stop() is False
    assert w.running and w.health()["status"] == "stopping"


def test_stop_cancels_and_rolls_back_an_inflight_batch(stack):
    w = stack.new()
    before = counts(stack)
    journal = w._journal

    def interrupted(db, event):
        journal(db, event)
        w._stop_event.set()

    w._journal = interrupted
    with pytest.raises(IndexerStopping):
        w.poll_once()
    assert counts(stack) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("indexer_poll_interval", 0),
        ("indexer_start_block", -1),
        ("chain_id", 0),
        ("indexer_rpc_timeout", 21),
        ("indexer_retry_max_interval", 1),
    ],
)
def test_invalid_bounds_are_rejected(field, value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize("failure", ["chain", "registry_code", "tracker_link", "none"])
def test_connection_is_published_only_after_full_validation(monkeypatch, failure):
    import app.services.indexer as module
    from web3 import Web3

    client = MagicMock()
    client.is_connected.return_value = True
    client.eth.chain_id = 1 if failure == "chain" else settings.chain_id
    client.eth.get_code.return_value = b"" if failure == "registry_code" else b"\x60"
    registry, tracker = MagicMock(), MagicMock()
    client.eth.contract.side_effect = [registry, tracker]
    tracker.functions.productRegistry.return_value.call.return_value = (
        "0x" + "9" * 40
        if failure == "tracker_link"
        else settings.product_registry_contract
    )
    factory = MagicMock(return_value=client)
    factory.is_address = Web3.is_address
    factory.to_checksum_address = Web3.to_checksum_address
    monkeypatch.setattr(module, "Web3", factory)
    worker = EventIndexer(rpc_url="https://private.invalid/token")
    if failure == "none":
        worker._connect()
        assert worker.w3 is client and worker.product_registry is registry
    else:
        with pytest.raises(ValueError):
            worker._connect()
        assert (
            worker.w3 is None
            and worker.product_registry is None
            and worker.shipment_tracker is None
        )


def test_shutdown_during_archive_rpc_failure_does_not_start_a_fallback_request():
    w = EventIndexer()
    w.w3 = MagicMock()
    contract = MagicMock()

    def fail(**_):
        w._stop_event.set()
        raise ConnectionError("https://private.invalid/token")

    contract.functions.getProduct.return_value.call.side_effect = fail
    with pytest.raises(IndexerStopping):
        w._registration_details(
            contract, {"args": {"productId": b"x" * 32}, "blockNumber": 1}
        )
    w.w3.eth.get_transaction.assert_not_called()


def test_start_is_idempotent_and_stop_is_interruptible(monkeypatch):
    w = EventIndexer()
    monkeypatch.setattr(w, "_run", lambda: w._stop_event.wait(2))
    w.start()
    first = w._thread
    try:
        w.start()
        assert w._thread is first
    finally:
        assert w.stop()
    assert not first.is_alive()


def test_health_transitions_are_structured_and_not_repeated(worker, caplog):
    import logging

    w, _ = worker
    caplog.set_level(logging.INFO, logger="veritras.indexer")
    w._log_health_transition()
    w._log_health_transition()
    w.last_processed_block = 90
    w._log_health_transition()
    w._log_health_transition()
    records = [r for r in caplog.records if r.message == "indexer_state_changed"]
    assert [r.status for r in records] == ["current", "catching_up"]
    assert records[1].lag_blocks == 10


def test_stop_tolerates_a_thread_that_failed_before_start():
    worker = EventIndexer()
    worker._thread = threading.Thread(target=lambda: None)
    assert worker.stop() and not worker.running


def test_all_health_responses_prevent_stale_http_caching(client_fixture):
    for path in ("/health", "/health/live", "/health/ready", "/health/indexer"):
        assert client_fixture.get(path).headers["cache-control"] == "no-store"


def test_liveness_does_not_wait_for_the_blocking_request_thread_pool():
    import inspect

    assert inspect.iscoroutinefunction(api.health_live)
