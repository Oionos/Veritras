"""Inspect/validate an isolated backup, migration and read-only backfill rehearsal."""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from sqlalchemy import create_engine, text
from web3 import Web3
from check_local_recovery import validate_local

TABLES = (
    "products",
    "shipments",
    "checkpoints",
    "custody_transfers",
    "chain_events",
    "chain_blocks",
    "indexer_cursors",
    "indexed_products",
    "product_aliases",
    "registration_attempts",
    "alembic_version",
)


def fingerprint(engine):
    counts = {}
    payload = {}
    with engine.connect() as db:
        for table in TABLES:
            rows = [
                dict(r) for r in db.execute(text(f"SELECT * FROM {table}")).mappings()
            ]
            encoded = sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)
            counts[table] = len(rows)
            payload[table] = encoded
    return {
        "counts": counts,
        "digest": hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database")
    parser.add_argument("--hold-writer-lock", action="store_true")
    args = parser.parse_args()
    if args.database and args.hold_writer_lock:
        parser.error("A restored database cannot hold the source writer lock")
    manifest = json.loads(Path(os.environ["DEPLOYMENT_MANIFEST"]).read_text())
    source, api, rpc = validate_local(os.environ, manifest)
    if Web3(Web3.HTTPProvider(rpc)).eth.chain_id != 31337:
        raise RuntimeError("Not the isolated chain")
    url = source
    if args.database:
        if not re.fullmatch(r"veritras_rehearsal_[0-9a-f]{8}", args.database):
            raise RuntimeError("Refusing a non-rehearsal database")
        url = source.set(database=args.database)
    engine = create_engine(url)
    try:
        if args.hold_writer_lock:
            from app.services.indexer import WRITER_LOCK

            # Keep the source cursor and journal at one committed boundary while
            # the external pg_dump/restore commands run. Polls update the cursor
            # timestamp even without new blocks, so independent snapshots race.
            with engine.begin() as db:
                db.execute(text("SET LOCAL statement_timeout = '30s'"))
                db.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"), {"key": WRITER_LOCK}
                )
                print(json.dumps(fingerprint(engine), sort_keys=True), flush=True)
                if sys.stdin.readline().strip() != "release":
                    raise RuntimeError("Rehearsal coordinator disconnected")
            return
        before = fingerprint(engine)
        if not args.database:
            print(json.dumps(before, sort_keys=True))
            return
        os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
        os.environ["PRODUCT_REGISTRY_CONTRACT"] = manifest["contracts"][
            "ProductRegistry"
        ]
        os.environ["SHIPMENT_TRACKER_CONTRACT"] = manifest["contracts"][
            "ShipmentTracker"
        ]
        os.environ["INDEXER_START_BLOCK"] = str(int(manifest["startBlock"]) - 1)
        import manage_schema

        manage_schema.engine = engine
        manage_schema.migrate(apply=True)
        manage_schema.require_current_schema()
        from sqlalchemy.orm import Session
        from app.services.indexer import EventIndexer
        import manage_identity
        import manage_indexer

        worker = EventIndexer()
        worker._connect()
        target = worker.w3.eth.block_number
        events = []
        # Local chain only: no operator-selected external RPC/database enters this drill.
        start = int(manifest["startBlock"])
        while start <= target:
            end = min(target, start + 99)
            events.extend(worker._fetch_events(start, end))
            start = end + 1
        with Session(engine) as db:
            worker._lock(db)
            identity = manage_identity.reconcile(worker, db, events, apply=False)
            history = manage_indexer.reconcile(worker, db, events, apply=False)
            db.rollback()
        if identity["conflicts"] or history["conflicts"]:
            raise RuntimeError("Rehearsal reconciliation found conflicts")
        after = fingerprint(engine)
        if before != after:
            raise RuntimeError("Dry-run reconciliation changed restored data")
        print(
            json.dumps(
                {"passed": True, **after, "identity": identity, "history": history},
                sort_keys=True,
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
