import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

import replay_private_restore as replay


@pytest.fixture
def harness(monkeypatch):
    import app.main as api
    # api_reads replaces the module's writer only for its private ASGI transport.
    monkeypatch.setattr(api, "indexer", api.indexer)
    clock = SimpleNamespace(now=0.0, pauses=[])
    monkeypatch.setattr(replay, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=lambda _: None))
    actual_sleep = asyncio.sleep

    async def pause(delay):
        if delay:
            clock.pauses.append(delay)
            clock.now += delay
        # ASGI/AnyIO also uses sleep(0) to yield between middleware tasks.
        await actual_sleep(0)

    monkeypatch.setattr(replay.asyncio, "sleep", pause)
    return clock


def serve(monkeypatch, *, faults=None, items=None, clock=None, late=False):
    calls, counts = [], {}
    faults = faults or {}
    items = [{"product_id": "PROD #private"}] if items is None else items

    def handler(request):
        assert request.url.host == "private-rehearsal.invalid" and request.method == "GET"
        path = request.url.raw_path.decode()
        calls.append(path)
        count = counts.get(path, 0)
        counts[path] = count + 1
        outcomes = faults.get(path, [])
        outcome = outcomes[min(count, len(outcomes) - 1)] if outcomes else 200
        if isinstance(outcome, Exception):
            raise outcome
        if outcome == "invalid_json":
            return httpx.Response(200, content=b"private-key-not-json")
        if outcome == "invalid_body":
            return httpx.Response(200, json=["private-row"])
        if late:
            clock.now += 2
        body = {"items": items, "total": len(items)} if path == "/products/?limit=1" else {"ok": True}
        return httpx.Response(outcome, json=body)

    monkeypatch.setattr(httpx, "ASGITransport", lambda **kwargs: httpx.MockTransport(handler))
    return calls


@pytest.mark.parametrize("path", ["/health/ready", "/products/PROD%20%23private/verify"])
def test_transient_private_readiness_and_api_failures_must_recover_before_acceptance(monkeypatch, harness, path):
    calls = serve(monkeypatch, faults={path: [503, 200]})
    result = asyncio.run(replay.api_reads(SimpleNamespace(), deadline=20))
    assert result["passed"] and result["representative_product_available"]
    assert result["checks"] == ["health_ready", "products", "shipments", "analytics_kpis",
                                "product_detail", "product_timeline", "product_verification"]
    assert result["attempts"] == 8 and calls.count(path) == 2
    assert calls.count("/products/?limit=1") == 1
    assert harness.pauses == [1]
    assert "PROD #private" not in json.dumps(result)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_private_api_permissions_or_missing_routes_are_never_retried(monkeypatch, harness, status):
    calls = serve(monkeypatch, faults={"/products/PROD%20%23private": [status]})
    with pytest.raises(replay.ReplayBlocked) as failure:
        asyncio.run(replay.api_reads(SimpleNamespace(), deadline=20))
    assert failure.value.diagnostics == {"api_route": "product_detail", "api_http_status": status,
                                         "api_failure_kind": "http_status", "api_attempts": 1}
    assert len(calls) == 5 and not harness.pauses
    assert "PROD" not in json.dumps(failure.value.diagnostics)


@pytest.mark.parametrize("outcome,kind", [(503, "http_status"),
                                        (httpx.ReadTimeout("private-url-key"), "timeout")])
def test_persistent_private_api_errors_fail_with_bounded_sanitized_diagnostics(monkeypatch, harness, outcome, kind):
    calls = serve(monkeypatch, faults={"/health/ready": [outcome]})
    with pytest.raises(replay.ReplayBlocked) as failure:
        asyncio.run(replay.api_reads(SimpleNamespace(), deadline=20))
    assert failure.value.diagnostics["api_route"] == "health_ready"
    assert failure.value.diagnostics["api_attempts"] == 3
    assert failure.value.diagnostics["api_failure_kind"] == kind
    assert len(calls) == 3 and harness.pauses == [1, 2]
    assert "private-url-key" not in json.dumps(failure.value.diagnostics)


@pytest.mark.parametrize("outcome", ["invalid_json", "invalid_body"])
def test_invalid_private_api_bodies_cannot_pass_or_be_retried(monkeypatch, harness, outcome):
    calls = serve(monkeypatch, faults={"/health/ready": [outcome]})
    with pytest.raises(replay.ReplayBlocked) as failure:
        asyncio.run(replay.api_reads(SimpleNamespace(), deadline=20))
    assert failure.value.diagnostics["api_failure_kind"] == outcome
    assert len(calls) == 1 and not harness.pauses
    assert "private-key" not in json.dumps(failure.value.diagnostics)


def test_private_api_retries_cannot_extend_the_remaining_recovery_deadline(monkeypatch, harness):
    calls = serve(monkeypatch, faults={"/health/ready": [503]})
    with pytest.raises(replay.ReplayBlocked) as failure:
        asyncio.run(replay.api_reads(SimpleNamespace(), deadline=1.1))
    assert failure.value.diagnostics["api_failure_kind"] == "deadline_exceeded"
    assert len(calls) == 2 and harness.pauses == [1] and harness.now == 1


def test_private_api_response_arriving_after_deadline_is_rejected(monkeypatch, harness):
    serve(monkeypatch, clock=harness, late=True)
    with pytest.raises(replay.ReplayBlocked) as failure:
        asyncio.run(replay.api_reads(SimpleNamespace(), deadline=1))
    assert failure.value.diagnostics["api_failure_kind"] == "deadline_exceeded"


def test_empty_private_database_does_not_fabricate_representative_reads(monkeypatch, harness):
    calls = serve(monkeypatch, items=[])
    result = asyncio.run(replay.api_reads(SimpleNamespace(), deadline=20))
    assert result["passed"] and not result["representative_product_available"]
    assert result["checks"] == ["health_ready", "products", "shipments", "analytics_kpis"]
    assert len(calls) == 4


def test_real_asgi_health_probe_can_warm_without_accepting_its_first_503(monkeypatch, harness, db_session):
    import app.main as api
    from app.core.config import settings
    from app.core.database import get_db
    from app.core.limiter import limiter

    monkeypatch.setattr(settings, "indexer_enabled", True)
    monkeypatch.setitem(api.app.dependency_overrides, get_db, lambda: db_session)
    checks = []

    def database_status(_):
        checks.append(True)
        return "timed_out" if len(checks) == 1 else "connected"

    monkeypatch.setattr(api, "_database_probe", SimpleNamespace(status=database_status))
    worker = SimpleNamespace(
        product_registry_address=settings.product_registry_contract,
        shipment_tracker_address=settings.shipment_tracker_contract,
        health=lambda: dict(status="current", ready=True, enabled=True, lag_blocks=0,
                            poll_interval_seconds=1, startup_timeout_seconds=120,
                            stale_after_seconds=120, head_stale_after_seconds=300,
                            max_lag_blocks=0, chain_id=11155111, confirmations=12),
    )
    limiter._storage.reset()
    try:
        result = asyncio.run(replay.api_reads(worker, deadline=20))
        assert result["passed"] and result["attempts"] == 5
        assert len(checks) == 2 and harness.pauses == [1]
    finally:
        limiter._storage.reset()


def test_live_recovery_rechecks_fresh_zero_lag_after_api_reads(monkeypatch, harness):
    ready = dict(status="current", ready=True, lag_blocks=0, target_head=100,
                 success_age_seconds=1, stale_after_seconds=120,
                 head_age_seconds=1, head_stale_after_seconds=300)
    states = iter([ready, dict(ready, status="catching_up", ready=False, lag_blocks=1), ready, ready])
    starts, stops, reads = [], [], []
    worker = SimpleNamespace(start=lambda: starts.append(True), stop=lambda: stops.append(True) or True,
                             health=lambda: next(states))

    async def api_read(_worker, *, deadline):
        reads.append(deadline)
        return {"passed": True}

    monkeypatch.setattr(replay, "api_reads", api_read)
    result = replay.replay_live(worker, 20)
    assert result["passed"] and result["lag_blocks"] == 0
    assert len(reads) == 2 and reads == [20, 20]
    assert len(starts) == len(stops) == 1


def test_public_api_failure_summary_rejects_unstructured_fields():
    import rehearse_hosted_recovery as hosted
    report = {"overall_result": "blocked", "state": "live_readiness_or_history_failed",
              "live_readiness": {"state": "private_api_read_failed", "api_route": "product_detail",
                                 "api_http_status": 503, "api_attempts": True,
                                 "api_failure_kind": "private-url-key", "private": "private-row"}}
    summary = hosted.console_summary(report)
    assert summary["live_readiness"] == {"state": "private_api_read_failed",
                                         "api_route": "product_detail", "api_http_status": 503}
    assert "private-url-key" not in json.dumps(summary) and "private-row" not in json.dumps(summary)
    assert hosted.report_exit_code(report) == 1
