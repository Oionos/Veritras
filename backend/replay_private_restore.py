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

from compare_recovery import checked_url, digest, fingerprint
from check_deployment_identity import rpc_failure
from environment_policy import environment
from manage_rehearsal_resources import private_json


class ReplayBlocked(Exception):
    def __init__(self, state, *, error=None, stage=None, start=None, end=None, attempts=None):
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


def confirmed_events(worker, target, target_hash, deadline):
    from app.core.config import settings
    from app.services.indexer import _hex

    if target < settings.indexer_start_block or reconciliation_header(worker, target) != target_hash:
        raise ReplayBlocked("canonical_target_mismatch")
    events, start, headers, failures = [], settings.indexer_start_block + 1, {}, 0
    while start <= target:
        if time.monotonic() >= deadline:
            raise ReplayBlocked("reconciliation_timeout")
        end = min(target, start + worker._batch_size - 1)
        try:
            batch = worker._fetch_events(start, end)
        except Exception as error:
            failures += 1
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
        start = end + 1
    if reconciliation_header(worker, target) != target_hash:
        raise ReplayBlocked("canonical_target_mismatch")
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


async def api_reads(worker):
    import httpx
    import app.main as api

    api.indexer = worker
    # No lifespan hook: the already-running private writer is the sole owner.
    # No public socket and no second indexer/exception worker is started here.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app),
        base_url="https://private-rehearsal.invalid",
        follow_redirects=True,
    ) as client:
        for route in (
            "/health/ready",
            "/products/?limit=1",
            "/shipments/?limit=1",
            "/analytics/kpis",
        ):
            response = await client.get(route)
            if response.status_code != 200 or not isinstance(response.json(), dict):
                raise ReplayBlocked("private_api_read_failed")
        products = (await client.get("/products/?limit=1")).json()
        items = products.get("items", [])
        if items:
            identifier = items[0]["product_id"]
            for suffix in ("", "/timeline", "/verify"):
                response = await client.get(f"/products/{identifier}{suffix}")
                if response.status_code != 200:
                    raise ReplayBlocked("private_api_read_failed")
        return {
            "passed": True,
            "representative_product_available": bool(items),
            "transport": "in_process_private_asgi",
            "public_listener": False,
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
                reads = asyncio.run(api_reads(worker))
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
        events = confirmed_events(worker, target, target_hash, deadline)
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
    private_json(args.output, result)
    print(json.dumps({"passed": result["passed"]}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
