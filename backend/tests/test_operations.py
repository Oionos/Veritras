import json
import logging
from datetime import datetime, timezone
import pytest
from app.services.operations import Operations
from app.core.logging import JsonFormatter
from monitor_operations import monitor, assess_counters
from check_migration_window import preflight


def test_counters_are_bounded_expire_and_reset():
    now = [0.0]
    metrics = Operations(lambda: now[0])
    for i in range(30):
        now[0] = i * 60
        metrics.request(status=500, duration_ms=20)
    state = metrics.snapshot()
    assert len(metrics.requests) == 15 and state["api_5xx"] == 15
    now[0] += 901
    assert metrics.snapshot()["api_5xx"] == 0
    assert state["storage"] == "process_memory" and state["reset_on_restart"]


def test_health_requests_do_not_dilute_business_error_count():
    metrics = Operations()
    metrics.request(status=500, duration_ms=20)
    metrics.request(status=503, duration_ms=10, business=False)
    s = metrics.snapshot()
    assert s["requests"] == 2 and s["api_5xx"] == 1 and s["api_requests"] == 1


def test_telemetry_rejects_input_and_identity_fields(client_fixture):
    valid = dict(
        metric="LCP",
        route="shipment_detail",
        value=123,
        environment="development",
        release="a" * 40,
    )
    assert client_fixture.post("/telemetry/browser", json=valid).status_code == 204
    for field in ("wallet", "token", "message", "url", "note", "signature", "user"):
        assert (
            client_fixture.post(
                "/telemetry/browser", json=dict(valid, **{field: "secret"})
            ).status_code
            == 422
        )
    for field, value in [
        ("environment", "production"),
        ("route", "/shipments/SECRET"),
        ("value", -1),
        ("value", 600001),
        ("release", "secret"),
    ]:
        assert (
            client_fixture.post(
                "/telemetry/browser", json=dict(valid, **{field: value})
            ).status_code
            == 422
        )


def test_public_operations_are_typed_aggregates(client_fixture):
    response = client_fixture.get("/health/operations")
    assert response.status_code == 200
    body = response.json()
    assert body["health"]["environment"] == "development"
    assert body["counters"]["reset_on_restart"]
    assert all(
        "url" not in metric and "release" not in metric
        for metric in body["counters"]["browser_metrics"]
    )
    assert response.headers["cache-control"] == "no-store"


def test_request_logs_do_not_include_paths_input_ip_or_arbitrary_extras(
    client_fixture, capfd, monkeypatch
):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    response = client_fixture.get("/products/SECRET-PRODUCT?token=SECRET-TOKEN")
    records = [
        json.loads(line)
        for line in capfd.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    request = next(r for r in reversed(records) if r.get("message") == "request")
    assert request["path"] == "/{product_id}"
    assert request["release"] == "a" * 40 and "client_ip" not in request
    assert request["request_id"] == response.headers["x-request-id"]
    assert "SECRET" not in json.dumps(request)
    record = logging.LogRecord(
        "veritras.test", logging.ERROR, __file__, 1, "failure", (), None
    )
    record.token = "SECRET"
    record.user = {"wallet": "SECRET"}
    try:
        raise ValueError("SECRET RPC https://credentials.invalid")
    except ValueError:
        import sys

        record.exc_info = sys.exc_info()
    output = JsonFormatter().format(record)
    assert "SECRET" not in output and "credentials.invalid" not in output
    assert "ValueError" in output


def test_monitor_requires_sustained_readiness_and_checks_stream():
    now = [0.0]
    calls = []

    def ready(*args, **kwargs):
        calls.append(1)
        return {
            "ready": len(calls) > 1,
            "state": "current" if len(calls) > 1 else "starting",
        }

    def sleep(seconds):
        now[0] += seconds

    result = monitor(
        "https://example.invalid",
        environment="testing",
        expect_indexer=True,
        grace=90,
        readiness=ready,
        fetch=lambda *a: (
            200,
            {
                "health": {
                    "status": "ready",
                    "database": "connected",
                    "environment": "testing",
                    "indexer": {"enabled": True},
                },
                "counters": {"api_requests": 10, "api_5xx": 0},
            },
        ),
        stream=lambda *a, **k: True,
        clock=lambda: now[0],
        sleep=sleep,
    )
    assert result["healthy"] and len(calls) == 4


def test_monitor_disabled_policy_is_expected_and_stream_failure_actionable():
    now = [0.0]
    result = monitor(
        "https://example.invalid",
        environment="production",
        expect_indexer=False,
        grace=90,
        readiness=lambda *a, **k: {"ready": True, "state": "disabled"},
        fetch=lambda *a: (
            200,
            {
                "health": {
                    "status": "ready",
                    "database": "connected",
                    "environment": "production",
                    "indexer": {"enabled": False},
                },
                "counters": {"api_requests": 3, "api_5xx": 3},
            },
        ),
        stream=lambda *a, **k: False,
        clock=lambda: now[0],
        sleep=lambda t: now.__setitem__(0, now[0] + t),
    )
    assert result["conditions"] == ["api_errors", "event_stream"]
    assert all("OPERATIONS.md" in action for action in result["actions"])


def test_monitor_stale_indexer_fails_without_business_or_stream_calls():
    now = [0.0]

    def fail(*args, **kwargs):
        raise AssertionError("No downstream probes while unavailable")

    result = monitor(
        "https://example.invalid",
        environment="testing",
        expect_indexer=True,
        grace=30,
        readiness=lambda *a, **k: {
            "ready": False,
            "state": "degraded",
            "reason": "poll_stale",
        },
        fetch=fail,
        stream=fail,
        clock=lambda: now[0],
        sleep=lambda t: now.__setitem__(0, now[0] + t),
    )
    assert (
        result["conditions"] == ["readiness"]
        and result["readiness"]["reason"] == "poll_stale"
    )


def test_invalid_counters_fail_closed():
    assert assess_counters({"counters": {"api_requests": 1, "api_5xx": 2}}) == [
        "diagnostics"
    ]


def test_migration_preflight_rejects_pending_ci_before_health(tmp_path):
    sql = tmp_path / "migration.sql"
    sql.write_text("CREATE TABLE example(id integer);")

    def pending(commit):
        raise RuntimeError("CI pending")

    def no_health(*a):
        raise AssertionError("Admission precedes warmup check")

    with pytest.raises(RuntimeError):
        preflight(
            candidate="a" * 40,
            current="b" * 40,
            origin="https://example.invalid",
            sql_file=sql,
            admission=pending,
            fetch=no_health,
        )


def test_migration_preflight_requires_awake_exact_prior_release(tmp_path):
    sql = tmp_path / "migration.sql"
    sql.write_text("CREATE TABLE example(id integer);")
    proof = lambda commit: {"commit": commit, "workflows": []}
    for code, commit in [(503, "b" * 40), (200, "c" * 40)]:
        with pytest.raises(ValueError):
            preflight(
                candidate="a" * 40,
                current="b" * 40,
                origin="https://example.invalid",
                sql_file=sql,
                admission=proof,
                fetch=lambda *a: (
                    code,
                    {
                        "status": "ready",
                        "release_commit": commit,
                        "database": "connected",
                        "environment": "production",
                    },
                ),
            )

    def fetch(url, timeout):
        return 200, dict(
            status="alive" if url.endswith("live") else "ready",
            database="connected",
            release_commit="b" * 40,
            environment="production",
        )

    result = preflight(
        candidate="a" * 40,
        current="b" * 40,
        origin="https://example.invalid",
        sql_file=sql,
        admission=proof,
        fetch=fetch,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert result["approved_for_coordination"] and result["not_authorization_to_apply"]
    assert result["expires_at"] == "2026-01-01T00:02:00+00:00"


@pytest.mark.asyncio
async def test_stream_failure_is_private_observable_and_releases_subscription(
    monkeypatch,
):
    from app.api.routes import analytics
    from app.services.operations import operations

    baseline = operations.snapshot()["streams"]

    def broken():
        raise RuntimeError("SECRET connection string")

    monkeypatch.setattr(analytics, "chain_revision", broken)
    response = await analytics.analytics_events()
    chunks = [chunk async for chunk in response.body_iterator]
    assert chunks == ["event: unavailable\ndata: {}\n\n"]
    result = operations.snapshot()["streams"]
    assert result["failures"] == baseline["failures"] + 1
    assert result["active"] == baseline["active"]


@pytest.mark.asyncio
async def test_stream_heartbeat_is_named_and_cancel_releases_subscription(monkeypatch):
    import asyncio
    from app.api.routes import analytics
    from app.services.operations import operations

    monkeypatch.setattr(analytics, "chain_revision", lambda: 0)

    async def timeout(awaitable, **kwargs):
        awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(analytics.asyncio, "wait_for", timeout)
    baseline = operations.snapshot()["streams"]["active"]
    response = await analytics.analytics_events()
    iterator = response.body_iterator
    assert await anext(iterator) == "event: resync\ndata: {}\n\n"
    assert "event: heartbeat" in await anext(iterator)
    await iterator.aclose()
    assert operations.snapshot()["streams"]["active"] == baseline


def test_monitor_rechecks_readiness_in_the_operations_snapshot():
    now = [0.0]
    result = monitor(
        "https://example.invalid",
        environment="testing",
        expect_indexer=True,
        grace=60,
        readiness=lambda *a, **k: {"ready": True, "state": "current"},
        fetch=lambda *a: (
            200,
            {
                "health": {
                    "status": "not_ready",
                    "database": "connected",
                    "environment": "testing",
                    "indexer": {"enabled": True},
                },
                "counters": {"api_requests": 1, "api_5xx": 0},
            },
        ),
        stream=lambda *a, **k: True,
        clock=lambda: now[0],
        sleep=lambda t: now.__setitem__(0, now[0] + t),
    )
    assert result["healthy"] is False and result["conditions"] == ["diagnostics"]
