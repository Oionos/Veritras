"""Bounded read-only release/readiness probe; never restarts services or prints errors/URLs."""

import argparse
import json
import math
import re
import ssl
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

STATES = {
    "disabled",
    "not_started",
    "starting",
    "catching_up",
    "current",
    "degraded",
    "stopping",
    "stopped",
}
REASONS = {
    "rpc_not_configured",
    "invalid_rpc_url",
    "invalid_contract_address",
    "chain_mismatch",
    "contract_not_deployed",
    "tracker_registry_mismatch",
    "initializing",
    "startup_timeout",
    "poll_stale",
    "cursor_unavailable",
    "chain_head_stalled",
    "awaiting_confirmation_depth",
    "progress_stalled",
    "backfill",
    "worker_stopped",
    "shutdown_requested",
    "writer_busy",
    "reconciliation_required",
    "initialization_failed",
    "poll_failed",
    "thread_start_failed",
    "worker_not_started",
    "indexing_disabled",
}


def validate_url(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("Use an HTTP(S) API origin without credentials, query or path")
    return value.rstrip("/")


def fetch_json(url, timeout):
    try:
        response = urlopen(
            Request(url, headers={"Accept": "application/json"}),
            timeout=timeout,
            context=ssl.create_default_context(),
        )
    except HTTPError as response:
        # Read 503 health responses too; other HTTP failures remain failures.
        with response:
            return _read_response(response)
    with response:
        return _read_response(response)


def _read_response(response):
    raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError("Health response exceeds limit")
    return response.status, json.loads(raw)


def probe(
    url,
    *,
    environment,
    chain_id=11155111,
    confirmations=12,
    expected_commit=None,
    expect_indexer=True,
    timeout=4,
    fetch=fetch_json
):
    result = {"ready": False, "state": "unavailable"}
    try:
        start = time.monotonic()
        live_code, live = fetch(url + "/health/live", timeout)
        remaining = timeout - (time.monotonic() - start)
        if remaining <= 0:
            return result
        ready_code, ready = fetch(url + "/health/ready", remaining)
        if any(
            body.get("environment") != environment or body.get("chain_id") != chain_id
            for body in (live, ready)
        ):
            return dict(result, state="environment_mismatch")
        if expected_commit and any(
            body.get("release_commit") != expected_commit for body in (live, ready)
        ):
            return dict(result, state="awaiting_deployment")
        indexer = ready["indexer"]
        state = indexer["status"]
        if state not in STATES:
            raise ValueError("Unknown indexer state")
        result["state"] = state
        if indexer.get("reason") in REASONS:
            result["reason"] = indexer["reason"]
        for field in ("lag_blocks", "last_processed_block", "target_head"):
            if type(indexer.get(field)) is int and indexer[field] >= 0:
                result[field] = indexer[field]
        if (
            live_code != 200
            or live.get("status") != "alive"
            or ready_code != 200
            or ready.get("status") != "ready"
            or ready.get("database") != "connected"
        ):
            return result
        if (
            indexer.get("enabled") is not expect_indexer
            or indexer.get("confirmation_policy") != "depth"
            or indexer.get("confirmations") != confirmations
        ):
            return dict(result, state="policy_mismatch")
        if not expect_indexer:
            return dict(result, ready=state == "disabled")
        if state != "current" or indexer.get("ready") is not True:
            return result
        head, target, cursor, lag, limit = (
            indexer[key]
            for key in (
                "chain_head",
                "target_head",
                "last_processed_block",
                "lag_blocks",
                "max_lag_blocks",
            )
        )
        if (
            any(type(n) is not int or n < 0 for n in (head, target, cursor, lag, limit))
            or target != max(0, head - confirmations)
            or cursor > target
            or lag != target - cursor
            or lag > limit
        ):
            return dict(result, state="inconsistent_progress")
        age, stale = indexer["success_age_seconds"], indexer["stale_after_seconds"]
        if (
            not all(type(n) in (float, int) and math.isfinite(n) for n in (age, stale))
            or not 0 <= age < stale
        ):
            return dict(result, state="stale_progress")
        return dict(result, ready=True)
    except Exception:
        # Provider/body/JSON/TLS errors can contain secret URLs. Never echo them.
        return dict(result, ready=False, state="invalid_or_unavailable_response")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--environment", required=True, choices=["production", "testing", "development"]
    )
    parser.add_argument("--chain-id", type=int, default=11155111)
    parser.add_argument("--confirmations", type=int, default=12)
    parser.add_argument("--expected-commit")
    parser.add_argument(
        "--expect-indexer", choices=["enabled", "disabled"], default="enabled"
    )
    parser.add_argument(
        "--deadline",
        type=float,
        default=0,
        help="Maximum total wait; zero is one bounded check",
    )
    parser.add_argument("--interval", type=float, default=15)
    parser.add_argument("--timeout", type=float, default=4)
    args = parser.parse_args()
    try:
        origin = validate_url(args.url)
        if (
            not 0 < args.timeout <= 10
            or not 0 < args.interval <= 60
            or not 0 <= args.deadline <= 900
            or args.chain_id <= 0
            or args.confirmations < 0
            or args.expected_commit
            and not re.fullmatch("[0-9a-f]{40}", args.expected_commit)
        ):
            raise ValueError("Invalid probe bounds or commit")
    except ValueError:
        print(json.dumps({"ready": False, "state": "invalid_configuration"}))
        return 2
    end = time.monotonic() + args.deadline
    while True:
        remaining = end - time.monotonic()
        result = probe(
            origin,
            environment=args.environment,
            chain_id=args.chain_id,
            confirmations=args.confirmations,
            expected_commit=args.expected_commit,
            expect_indexer=args.expect_indexer == "enabled",
            timeout=(
                min(args.timeout, max(0.01, remaining))
                if args.deadline
                else args.timeout
            ),
        )
        print(json.dumps(result, sort_keys=True), flush=True)
        if result["ready"]:
            return 0
        if not args.deadline or time.monotonic() >= end:
            return 1
        time.sleep(min(args.interval, max(0, end - time.monotonic())))


if __name__ == "__main__":
    raise SystemExit(main())
