"""Private recovery worker process. No hosted service, wallet or public listener.

The coordinator must verify provider ownership before launching each process.
Existing local-chain helpers retain their separate localhost/chain guards.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time
from urllib.parse import quote

from compare_recovery import checked_url, digest, fingerprint
from check_deployment_identity import rpc_failure
from environment_policy import environment
from manage_rehearsal_resources import private_json

SCAN_PROGRESS_FIELDS = (
    "ranges_completed", "last_completed_block", "target_block", "from_block", "to_block",
    "batch_size", "events_count", "rpc_retries",
)
SCAN_STATES = {"events", "retry", "range_completed", "canonical_recheck", "complete"}
API_ROUTES = {"health_ready", "products", "shipments", "analytics_kpis",
              "product_detail", "product_timeline", "product_verification"}
API_FAILURES = {"http_status", "timeout", "request_failed", "invalid_json",
                "invalid_body", "invalid_identifier", "deadline_exceeded"}


def safe_api_failure(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for field, allowed in (("api_route", API_ROUTES), ("api_failure_kind", API_FAILURES)):
        if type(value.get(field)) is str and value[field] in allowed:
            result[field] = value[field]
    if type(value.get("api_http_status")) is int and 100 <= value["api_http_status"] <= 599:
        result["api_http_status"] = value["api_http_status"]
    if type(value.get("api_attempts")) is int and 1 <= value["api_attempts"] <= 3:
        result["api_attempts"] = value["api_attempts"]
    return result


def scan_progress_path(output):
    return Path(output).with_suffix(".progress.json")


def safe_scan_progress(value):
    if not isinstance(value, dict):
        return {}
    result = {key: value[key] for key in SCAN_PROGRESS_FIELDS
              if type(value.get(key)) is int and 0 <= value[key] < 2**63}
    state = value.get("scan_state")
    if type(state) is str and state in SCAN_STATES:
        result["scan_state"] = state
    return result


def read_scan_progress(output):
    """Read only bounded counters from the atomic private worker checkpoint."""
    try:
        path = scan_progress_path(output)
        if path.stat().st_size > 8192:
            return {}
        return safe_scan_progress(json.loads(path.read_text()))
    except (OSError, ValueError, TypeError):
        return {}


class ReplayBlocked(Exception):
    def __init__(self, state, *, error=None, stage=None, start=None, end=None, attempts=None,
                 api_route=None, api_status=None, api_failure=None, api_attempts=None):
        super().__init__(state)
        self.diagnostics = {}
        if error is not None:
            details = rpc_failure(error, stage)
            self.diagnostics = {key: value for key, value in details.items()
                                if key not in {"verified", "state"}}
        if type(start) is int and type(end) is int and 0 <= start <= end:
            self.diagnostics.update(from_block=start, to_block=end)
        if type(attempts) is int and 1 <= attempts <= 5:
            self.diagnostics["attempts"] = attempts
        self.diagnostics.update(safe_api_failure({"api_route": api_route,
                                                "api_http_status": api_status,
                                                "api_failure_kind": api_failure,
                                                "api_attempts": api_attempts}))


def retry_pause(failures, deadline, timeout_state):
    delay = min(2 ** (failures - 1), 8)
    if time.monotonic() + delay >= deadline:
        raise ReplayBlocked(timeout_state)
    time.sleep(delay)


def reconciliation_header(worker, number):
    try:
        return worker._header(number)
    except Exception as error:
        raise ReplayBlocked("reconciliation_rpc_failed", error=error,
                            stage="reconciliation_header", start=number, end=number) from None


def validate_private_target(manifest, env):
    target = manifest["target"]
    url = checked_url(env["DATABASE_URL"], target)
    if (
        not re.fullmatch(r"veritras_restore_[a-z0-9_]{8,64}", url.database)
        or env.get("RENDER") == "true"
        or manifest.get("private_rehearsal") is not True
        or env.get("ENVIRONMENT") != manifest.get("environment")
        or not re.fullmatch(r"br-[a-zA-Z0-9_-]+", manifest.get("branch_id", ""))
    ):
        raise ReplayBlocked("unsafe_private_target")
    expected = environment(manifest["environment"])
    if (
        str(expected["chain_id"]) != env.get("CHAIN_ID")
        or env.get("PRODUCT_REGISTRY_CONTRACT", "").lower()
        != expected["registry"].lower()
        or env.get("SHIPMENT_TRACKER_CONTRACT", "").lower()
        != expected["tracker"].lower()
        or str(expected["start_block"]) != env.get("INDEXER_START_BLOCK")
        or str(expected["confirmations"]) != env.get("INDEXER_CONFIRMATIONS")
    ):
        raise ReplayBlocked("private_scope_mismatch")
    return expected


def confirmed_events(worker, target, target_hash, deadline, *, progress=None):
    from app.core.config import settings
    from app.services.indexer import _hex

    if target < settings.indexer_start_block or reconciliation_header(worker, target) != target_hash:
        raise ReplayBlocked("canonical_target_mismatch")
    events, start, headers, failures = [], settings.indexer_start_block + 1, {}, 0
    max_batch = worker._batch_size
    ranges, retries = 0, 0

    def record(state, first, last, completed):
        if progress:
            progress({"scan_state": state, "ranges_completed": ranges,
                      "last_completed_block": completed, "target_block": target,
                      "from_block": first, "to_block": last,
                      "batch_size": worker._batch_size, "events_count": len(events),
                      "rpc_retries": retries})

    while start <= target:
        if time.monotonic() >= deadline:
            raise ReplayBlocked("reconciliation_timeout")
        end = min(target, start + worker._batch_size - 1)
        record("events", start, end, start - 1)
        try:
            batch = worker._fetch_events(start, end)
        except Exception as error:
            failures += 1
            retries += 1
            record("retry", start, end, start - 1)
            if failures >= 5:
                raise ReplayBlocked("reconciliation_rpc_failed", error=error,
                                    stage="reconciliation_events", start=start, end=end, attempts=failures) from None
            retry_pause(failures, deadline, "reconciliation_timeout")
            continue
        failures = 0
        for event in batch:
            number = event["blockNumber"]
            if number not in headers:
                headers[number] = reconciliation_header(worker, number)
            if headers[number] != _hex(event["blockHash"]):
                raise ReplayBlocked("canonical_target_mismatch")
        events.extend(batch)
        if len(events) > 100000:
            raise ReplayBlocked("reconciliation_event_budget_exceeded")
        ranges += 1
        # _fetch_events reduces its range after errors. Recover after successful
        # reads, as normal indexing does, so transient errors cannot permanently
        # turn the rest of a historical scan into one-block requests.
        worker._batch_size = min(max_batch, worker._batch_size * 2)
        record("range_completed", start, end, end)
        start = end + 1
    record("canonical_recheck", target, target, target)
    if reconciliation_header(worker, target) != target_hash:
        raise ReplayBlocked("canonical_target_mismatch")
    record("complete", target, target, target)
    return events


def reconcile_private(
    worker, session_factory, events, *, context, approved_digest, plan_path
):
    import manage_identity
    import manage_indexer

    with session_factory() as db:
        try:
            worker._lock(db)
            history = manage_indexer.reconcile(worker, db, events, apply=False)
            if history["conflicts"]:
                private_json(plan_path, {"history": history, "context": context})
                raise ReplayBlocked("reconciliation_conflicts")
            # Preview the dependent identity plan inside the same uncommitted
            # transaction. Without exact approval this entire preview rolls back.
            manage_indexer.reconcile(worker, db, events, apply=True)
            identity = manage_identity.reconcile(worker, db, events, apply=False)
            plan = {"context": context, "history": history, "identity": identity}
            plan_digest = digest(plan)
            private_json(plan_path, plan)
            summary = {
                "plan_digest": plan_digest,
                "history_matches": history["matched_rows"],
                "identity_changes": len(identity["changes"]),
                "applied": False,
            }
            if identity["conflicts"]:
                raise ReplayBlocked("reconciliation_conflicts")
            changes = bool(history["matched_rows"] or identity["changes"])
            if changes and approved_digest != plan_digest:
                return dict(
                    summary, state="reconciliation_review_required", passed=False
                )
            if changes:
                manage_identity.reconcile(worker, db, events, apply=True)
                if worker._header(context["target_block"]) != context["target_hash"]:
                    raise ReplayBlocked("canonical_target_mismatch")
                db.commit()
                summary["applied"] = True
            return dict(summary, state="reviewed", passed=True)
        finally:
            db.rollback()


class PinnedEth:
    def __init__(self, eth, head):
        self.eth, self.block_number = eth, head

    def __getattr__(self, name):
        return getattr(self.eth, name)


class PinnedWeb3:
    def __init__(self, w3, head):
        self.w3, self.eth = w3, PinnedEth(w3.eth, head)

    def __getattr__(self, name):
        return getattr(self.w3, name)


def replay_fixed(worker, target, target_hash, confirmations, deadline):
    if (
        worker.w3.eth.block_number - confirmations < target
        or worker._header(target) != target_hash
    ):
        raise ReplayBlocked("canonical_target_mismatch")
    worker.w3 = PinnedWeb3(worker.w3, target + confirmations)
    failures = 0
    while time.monotonic() < deadline:
        try:
            worker.poll_once()
            failures = 0
        except Exception as error:
            failures += 1
            if failures >= 5:
                raise ReplayBlocked("fixed_replay_failed", error=error, stage="replay_poll", attempts=failures) from None
            retry_pause(failures, deadline, "replay_timeout")
            continue
        if worker.last_processed_block == target:
            if worker._header(target) != target_hash:
                raise ReplayBlocked("canonical_target_mismatch")
            return
    raise ReplayBlocked("replay_timeout")


async def api_reads(worker, *, deadline=None):
    import httpx
    import app.main as api

    api.indexer = worker
    deadline = min(deadline if deadline is not None else float("inf"), time.monotonic() + 120)
    checks, total_attempts = [], 0
    # No lifespan hook: the already-running private writer is the sole owner.
    # No public socket and no second indexer/exception worker is started here.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app, raise_app_exceptions=False),
        base_url="https://private-rehearsal.invalid",
        follow_redirects=True,
    ) as client:
        async def read(path, route):
            nonlocal total_attempts
            for attempt in range(1, 4):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReplayBlocked("private_api_read_failed", api_route=route,
                                        api_failure="deadline_exceeded", api_attempts=attempt)
                total_attempts += 1
                status = None
                try:
                    response = await asyncio.wait_for(client.get(path), timeout=min(10, remaining))
                    status = response.status_code
                except (asyncio.TimeoutError, httpx.TimeoutException):
                    failure = "timeout"
                except Exception:
                    failure = "request_failed"
                else:
                    if time.monotonic() > deadline:
                        raise ReplayBlocked("private_api_read_failed", api_route=route,
                                            api_failure="deadline_exceeded", api_attempts=attempt)
                    if status == 200:
                        try:
                            body = response.json()
                        except (ValueError, TypeError):
                            raise ReplayBlocked("private_api_read_failed", api_route=route,
                                                api_failure="invalid_json", api_attempts=attempt) from None
                        if not isinstance(body, dict):
                            raise ReplayBlocked("private_api_read_failed", api_route=route,
                                                api_failure="invalid_body", api_attempts=attempt)
                        checks.append(route)
                        return body
                    failure = "http_status"
                error = ReplayBlocked("private_api_read_failed", api_route=route, api_status=status,
                                      api_failure=failure, api_attempts=attempt)
                if attempt == 3 or status is not None and status not in {408, 425, 429, 500, 502, 503, 504}:
                    raise error
                delay = attempt
                if time.monotonic() + delay >= deadline:
                    raise ReplayBlocked("private_api_read_failed", api_route=route,
                                        api_failure="deadline_exceeded", api_attempts=attempt) from None
                await asyncio.sleep(delay)

        await read("/health/ready", "health_ready")
        products = await read("/products/?limit=1", "products")
        await read("/shipments/?limit=1", "shipments")
        await read("/analytics/kpis", "analytics_kpis")
        items = products.get("items")
        if not isinstance(items, list):
            raise ReplayBlocked("private_api_read_failed", api_route="products", api_failure="invalid_body")
        if items:
            identifier = items[0].get("product_id") if isinstance(items[0], dict) else None
            if not isinstance(identifier, str) or not 0 < len(identifier) <= 100:
                raise ReplayBlocked("private_api_read_failed", api_route="products", api_failure="invalid_identifier")
            try:
                identifier = quote(identifier, safe="")
            except UnicodeError:
                raise ReplayBlocked("private_api_read_failed", api_route="products", api_failure="invalid_identifier") from None
            for suffix, route in (("", "product_detail"), ("/timeline", "product_timeline"),
                                  ("/verify", "product_verification")):
                await read(f"/products/{identifier}{suffix}", route)
        return {
            "passed": True,
            "representative_product_available": bool(items),
            "transport": "in_process_private_asgi",
            "public_listener": False,
            "checks": checks,
            "attempts": total_attempts,
        }


def replay_live(worker, deadline):
    worker.start()
    try:
        while time.monotonic() < deadline:
            state = worker.health()
            if (
                state["status"] == "current"
                and state["ready"]
                and state["lag_blocks"] == 0
                and state["success_age_seconds"] < state["stale_after_seconds"]
                and state["head_age_seconds"] < state["head_stale_after_seconds"]
            ):
                reads = asyncio.run(api_reads(worker, deadline=deadline))
                # A new block can arrive during the API requests. Require a
                # fresh, current zero-lag observation again before accepting.
                state = worker.health()
                if not (state["status"] == "current" and state["ready"]
                        and state["lag_blocks"] == 0
                        and state["success_age_seconds"] < state["stale_after_seconds"]
                        and state["head_age_seconds"] < state["head_stale_after_seconds"]):
                    continue
                return {
                    "passed": True,
                    "target_block": state["target_head"],
                    "lag_blocks": 0,
                    "state": "current",
                    "api_reads": reads,
                }
            time.sleep(1)
        raise ReplayBlocked("live_readiness_timeout")
    finally:
        if not worker.stop():
            raise ReplayBlocked("private_worker_shutdown_failed")


def journal_prefix(engine, target):
    from sqlalchemy import text

    with engine.connect() as connection:
        rows = connection.execution_options(
            stream_results=True, max_row_buffer=1000
        ).execute(
            text(
                """
            SELECT to_jsonb(t)::text FROM
              (SELECT event_id,block_hash,payload FROM chain_events
               WHERE canonical=true AND block_number<=:target ORDER BY event_id COLLATE "C") t
            """
            ),
            {"target": target},
        )
        result = hashlib.sha256()
        for (value,) in rows:
            value = value.encode()
            result.update(len(value).to_bytes(8, "big"))
            result.update(value)
        return result.hexdigest()


def execute(args):
    manifest = json.loads(args.manifest.read_text())
    expected = validate_private_target(manifest, os.environ)
    # Imports happen only after explicit target validation; never fall back to
    # application defaults or create a SQLite database during a failed preflight.
    from app.core.database import engine, SessionLocal
    from app.core.config import settings
    from app.services.indexer import EventIndexer
    from sqlalchemy import text
    from manage_schema import require_current_schema

    try:
        require_current_schema()
    except Exception:
        raise ReplayBlocked("restored_schema_admission_failed") from None
    if args.phase == "reconcile" and settings.indexer_enabled:
        raise ReplayBlocked("reconciliation_requires_disabled_writer")
    if args.phase != "reconcile" and not settings.indexer_enabled:
        raise ReplayBlocked("replay_requires_private_writer")
    worker, deadline = EventIndexer(), time.monotonic() + args.timeout
    worker._connect()
    target = args.target_block
    if target is None:
        target = worker.w3.eth.block_number - expected["confirmations"]
    target_hash = worker._header(target)
    if (
        target > worker.w3.eth.block_number - expected["confirmations"]
        or args.target_hash
        and args.target_hash != target_hash
    ):
        raise ReplayBlocked("canonical_target_mismatch")
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    common = {
        "target_block": target,
        "target_hash": target_hash,
        "schema_revision": revision,
    }
    if args.phase == "reconcile":
        events = confirmed_events(
            worker, target, target_hash, deadline,
            progress=lambda value: private_json(scan_progress_path(args.output), value),
        )
        context = {
            **common,
            "candidate_sha": manifest["candidate_sha"],
            "chain_id": expected["chain_id"],
            "registry": expected["registry"],
            "tracker": expected["tracker"],
            "start_block": expected["start_block"],
            "confirmations": expected["confirmations"],
        }
        return {
            **common,
            "scan_progress": read_scan_progress(args.output),
            **reconcile_private(
                worker,
                SessionLocal,
                events,
                context=context,
                approved_digest=args.approved_digest,
                plan_path=args.output.with_name("reconciliation-plan.json"),
            ),
        }
    if args.phase == "fixed":
        replay_fixed(worker, target, target_hash, expected["confirmations"], deadline)
        snapshot = fingerprint(
            engine, expected_database=manifest["target"]["database"], stable_cursor=True
        )
        return {
            **common,
            "passed": True,
            "snapshot_digest": digest(snapshot),
            "journal_prefix_digest": journal_prefix(engine, target),
        }
    before = journal_prefix(engine, target)
    result = replay_live(worker, deadline)

    # stop() sets the cancellation flag; use bounded read-only RPC calls rather
    # than the writer's intentionally cancelled _header() helper after shutdown.
    def canonical_hash(number):
        return "0x" + worker.w3.eth.get_block(number)["hash"].hex().removeprefix("0x")

    if (
        before != journal_prefix(engine, target)
        or canonical_hash(target) != target_hash
    ):
        raise ReplayBlocked("canonical_history_changed_during_live_check")
    return {
        **result,
        "target_hash": canonical_hash(result["target_block"]),
        "schema_revision": revision,
        "fixed_target_block": target,
        "fixed_target_hash": target_hash,
        "journal_prefix_digest": before,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=["reconcile", "fixed", "live"], required=True
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--target-block", type=int)
    parser.add_argument("--target-hash")
    parser.add_argument("--approved-digest", default="")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        if not 1 <= args.timeout <= 1200:
            raise ReplayBlocked("invalid_replay_deadline")
        result = execute(args)
    except ReplayBlocked as error:
        result = {"passed": False, "state": str(error), **error.diagnostics}
    except Exception:
        result = {"passed": False, "state": "private_worker_failed"}
    if progress := read_scan_progress(args.output):
        result["scan_progress"] = progress
    private_json(args.output, result)
    print(json.dumps({"passed": result["passed"]}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
