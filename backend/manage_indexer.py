"""Review and optionally attribute legacy history to exact authoritative logs.

Default is read-only. --apply tags uniquely matched rows, never deletes/merges
rows or grants ownership. Any ambiguity aborts the entire update.
"""

import argparse
import json
from datetime import timezone

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.product_id import canonical_product_id
from app.models.shipment import Checkpoint, CustodyTransfer
from app.services.indexer import (
    EventIndexer,
    ReconciliationRequired,
    _hex,
    timestamp_to_datetime,
)


def reconcile(worker, db, events, apply=False):
    candidates = {"CheckpointRecorded": [], "CustodyTransferred": []}
    for event in events:
        if event["event"] in candidates:
            candidates[event["event"]].append(event)
    matches, conflicts = [], []
    for model, kind in (
        (Checkpoint, "CheckpointRecorded"),
        (CustodyTransfer, "CustodyTransferred"),
    ):
        for row in db.query(model).filter_by(source_event_id=None).all():
            found = []
            for event in candidates[kind]:
                args = event["args"]
                try:
                    same_product = canonical_product_id(row.product_id) == bytes(
                        args["productId"]
                    )
                except ValueError:
                    same_product = False
                if (
                    not same_product
                    or row.tx_hash.lower() != _hex(event["transactionHash"])
                    or row.block_number != event["blockNumber"]
                ):
                    continue
                timestamp = (
                    row.timestamp.replace(tzinfo=timezone.utc)
                    if row.timestamp.tzinfo is None
                    else row.timestamp
                )
                if timestamp != timestamp_to_datetime(args["timestamp"]):
                    continue
                if kind == "CheckpointRecorded":
                    same = (
                        row.location == args["location"]
                        and row.status == str(args["status"])
                        and row.handler_address.lower() == args["handler"].lower()
                        and (row.notes or "") == args["notes"]
                    )
                else:
                    same = (
                        row.from_address.lower() == args["from"].lower()
                        and row.to_address.lower() == args["to"].lower()
                    )
                if same:
                    identity = f"{settings.chain_id}:{event['address'].lower()}:{_hex(event['transactionHash'])}:{event['logIndex']}"
                    found.append(identity)
            if (
                len(found) != 1
                or db.query(model).filter_by(source_event_id=found[0]).first()
            ):
                conflicts.append(
                    {
                        "table": model.__tablename__,
                        "id": row.id,
                        "matching_logs": len(found),
                    }
                )
            else:
                matches.append((row, found[0]))
    identities = [identity for _, identity in matches]
    if len(identities) != len(set(identities)):
        conflicts.append(
            {
                "reason": "Several legacy rows match the same log; explicit duplicate review required"
            }
        )
    report = {"matched_rows": len(matches), "conflicts": conflicts, "applied": False}
    if apply:
        if conflicts:
            raise ReconciliationRequired(
                "Legacy history has conflicts; no rows were changed"
            )
        for row, identity in matches:
            row.source_event_id = identity
        db.flush()
        report["applied"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    worker = EventIndexer()
    worker._connect()
    target = worker.w3.eth.block_number - settings.indexer_confirmations
    if target < settings.indexer_start_block:
        raise ReconciliationRequired("Confirmed head is before deployment anchor")
    with SessionLocal() as db:
        worker._lock(db)
        end_hash = worker._header(target)
        events, start = [], settings.indexer_start_block + 1
        while start <= target:
            end = min(target, start + worker._batch_size - 1)
            try:
                batch = worker._fetch_events(start, end)
            except Exception:
                if end == start:
                    raise
                continue
            for event in batch:
                if _hex(event["blockHash"]) != worker._header(event["blockNumber"]):
                    raise RuntimeError("Chain changed during reconciliation")
            events.extend(batch)
            start = end + 1
        report = reconcile(worker, db, events, apply=args.apply)
        if worker._header(target) != end_hash:
            raise RuntimeError("Chain changed during reconciliation")
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    # Provider errors may contain private RPC endpoints. Fail without echoing them.
    try:
        main()
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "applied": False}))
        raise SystemExit(1)
