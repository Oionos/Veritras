"""Read-only scheduled operations check. Native Actions failures provide alerts.

No service restart, paid keep-alive, external recipients, business writes or secrets.
"""

import argparse
import json
import ssl
import time
from urllib.request import Request, urlopen
from check_health import probe, validate_url, fetch_json

ACTIONS = {
    "readiness": "Inspect health/indexer reason and Render runtime logs; see OPERATIONS.md#incident-response.",
    "api_errors": "Inspect structured request error_type/request_id and release; see OPERATIONS.md#incident-response.",
    "event_stream": "Inspect event_stream_unavailable and database connectivity; see OPERATIONS.md#incident-response.",
    "diagnostics": "Check deployment/schema and health/operations response; see OPERATIONS.md#incident-response.",
}


def stream_probe(origin, timeout=12):
    start = time.monotonic()
    with urlopen(
        Request(origin + "/analytics/events", headers={"Accept": "text/event-stream"}),
        timeout=timeout,
        context=ssl.create_default_context(),
    ) as response:
        if response.status != 200 or not response.headers.get(
            "Content-Type", ""
        ).startswith("text/event-stream"):
            return False
        size = 0
        while time.monotonic() - start < timeout:
            line = response.readline(4097)
            size += len(line)
            if not line or len(line) > 4096 or size > 16384:
                return False
            if line.strip() in (b": heartbeat", b"event: heartbeat"):
                return True
            if line.strip() == b"event: unavailable":
                return False
    return False


def assess_counters(body):
    counters = body["counters"]
    requests, errors = counters["api_requests"], counters["api_5xx"]
    if (
        any(type(v) is not int or v < 0 for v in (requests, errors))
        or errors > requests
    ):
        return ["diagnostics"]
    return ["api_errors"] if errors >= 3 else []


def monitor(
    origin,
    *,
    environment,
    expect_indexer,
    grace=240,
    interval=15,
    timeout=15,
    readiness=probe,
    fetch=fetch_json,
    stream=stream_probe,
    clock=time.monotonic,
    sleep=time.sleep
):
    deadline = clock() + grace
    consecutive = 0
    observed = {"ready": False, "state": "unavailable"}
    while clock() < deadline:
        observed = readiness(
            origin,
            environment=environment,
            expect_indexer=expect_indexer,
            timeout=timeout,
        )
        consecutive = consecutive + 1 if observed["ready"] else 0
        if consecutive >= 3:
            break
        sleep(min(interval, max(0, deadline - clock())))
    failures = []
    if consecutive < 3:
        failures.append("readiness")
    else:
        try:
            code, body = fetch(origin + "/health/operations", timeout)
            if (
                code != 200
                or body["health"]["status"] != "ready"
                or body["health"]["database"] != "connected"
                or body["health"]["environment"] != environment
                or body["health"]["indexer"]["enabled"] is not expect_indexer
            ):
                failures.append("diagnostics")
            else:
                failures.extend(assess_counters(body))
        except Exception:
            failures.append("diagnostics")
        try:
            if not stream(origin, timeout=12):
                failures.append("event_stream")
        except Exception:
            failures.append("event_stream")
    # Keep only allowlisted operational state; never echo arbitrary response text/URLs.
    safe = {
        key: observed[key]
        for key in (
            "ready",
            "state",
            "reason",
            "lag_blocks",
            "last_processed_block",
            "target_head",
        )
        if key in observed
    }
    return dict(
        healthy=not failures,
        environment=environment,
        expected_indexer=expect_indexer,
        readiness=safe,
        conditions=sorted(set(failures)),
        actions=[ACTIONS[f] for f in sorted(set(failures))],
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, type=validate_url)
    parser.add_argument(
        "--environment", required=True, choices=["production", "testing"]
    )
    parser.add_argument(
        "--expect-indexer", required=True, choices=["enabled", "disabled"]
    )
    parser.add_argument(
        "--grace", type=int, default=240, choices=range(30, 301), metavar="30..300"
    )
    args = parser.parse_args()
    result = monitor(
        args.url,
        environment=args.environment,
        expect_indexer=args.expect_indexer == "enabled",
        grace=args.grace,
    )
    print(json.dumps(result, sort_keys=True))
    if not result["healthy"]:
        for condition in result["conditions"]:
            print("::error title=Veritras " + condition + "::" + ACTIONS[condition])
    raise SystemExit(0 if result["healthy"] else 1)
