"""Review canonical identities; default is read-only, --apply is atomic.

Reads confirmed registration logs from the configured deployment anchor. Names
never establish identity. Conflicts abort the entire apply. Duplicate rows are
archived, their references moved, and their old public URLs retained as aliases.
Unproven legacy manufacturers never receive ownership.
"""

import argparse
import json
from collections import defaultdict

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.product_id import canonical_hex
from app.models.product import Product, ProductAlias
from app.models.chain import IndexedProduct
from app.models.shipment import Checkpoint, CustodyTransfer, Shipment
from app.services.identity import IDENTITY_FIELDS, scope_values, assign_identity
from app.services.indexer import (
    EventIndexer,
    ReconciliationRequired,
    _hex,
    PRODUCT_FIELDS,
)


def reconcile(worker, db, events, *, apply=False):
    """events must be complete, confirmed, canonical logs verified by the caller."""
    registrations = defaultdict(list)
    for event in events:
        if event["event"] == "ProductRegistered":
            if event[
                "address"
            ].lower() != worker.product_registry_address.lower() or event.get(
                "removed"
            ):
                raise ReconciliationRequired("Unexpected registration emitter")
            registrations[_hex(event["args"]["productId"])].append(event)
    groups, conflicts, actions = defaultdict(list), [], []
    for product in (
        db.query(Product)
        .filter(Product.registration_status != "superseded")
        .with_for_update()
        .all()
    ):
        if product.chain_id is not None and (
            product.chain_id != settings.chain_id
            or product.registry_address != worker.product_registry_address.lower()
        ):
            continue
        try:
            key = canonical_hex(product.product_id)
            values = scope_values(
                key,
                registry=worker.product_registry_address,
                tracker=worker.shipment_tracker_address,
            )
            existing = {field: getattr(product, field) for field in IDENTITY_FIELDS}
            if (
                any(value is not None for value in existing.values())
                and existing != values
            ):
                raise ValueError(
                    "Stored identity disagrees with display ID or configured tracker"
                )
            groups[key].append(product)
        except ValueError as error:
            conflicts.append({"product_id": product.product_id, "reason": str(error)})
    for key, rows in sorted(groups.items()):
        evidence = registrations[key]
        try:
            if len(evidence) > 1:
                raise ValueError("Several canonical registration logs claim this item")
            bindings = (
                db.query(IndexedProduct)
                .filter(IndexedProduct.product_id.in_([p.product_id for p in rows]))
                .all()
            )
            if len(bindings) > 1 or any(
                b.scope != worker.scope or b.product_key != key for b in bindings
            ):
                raise ValueError("Conflicting projection bindings")
            if len(rows) > 1 and not evidence:
                raise ValueError(
                    "Duplicate identity lacks authoritative registration evidence"
                )
            event = evidence[0] if evidence else None
            for product in rows:
                if db.get(ProductAlias, product.product_id):
                    raise ValueError(
                        "An active product is shadowed by a conflicting public alias"
                    )
                if event:
                    args = event["args"]
                    if (
                        product.manufacturer_address.lower()
                        != args["manufacturer"].lower()
                        or product.name != args["name"]
                    ):
                        raise ValueError(
                            "Registration manufacturer or name disagrees with a candidate"
                        )
                    if product.block_number > 0 and (
                        product.block_number != event["blockNumber"]
                        or product.tx_hash.lower() != _hex(event["transactionHash"])
                    ):
                        raise ValueError(
                            "Legacy transaction or block disagrees with registration"
                        )
                    if product.owner_address and (
                        product.ownership_source not in {"signed_draft", "chain_event"}
                        or product.owner_address.lower() != args["manufacturer"].lower()
                    ):
                        raise ValueError("Ownership disagrees with registration")
                elif (
                    product.block_number > 0
                    or product.ownership_source == "chain_event"
                ):
                    raise ValueError(
                        "Claimed registration has no confirmed canonical log"
                    )
            if not event and any(p.ownership_source != "signed_draft" for p in rows):
                # Unknown historical records stay unknown. No inferred owner or scope.
                continue
            if len(rows) > 1:
                if (
                    db.query(Shipment)
                    .filter(Shipment.product_id.in_([p.product_id for p in rows]))
                    .count()
                    > 1
                ):
                    raise ValueError(
                        "Duplicate shipment lifecycles require explicit review"
                    )
                for model in (Checkpoint, CustodyTransfer):
                    if (
                        db.query(model)
                        .filter(
                            model.product_id.in_([p.product_id for p in rows]),
                            model.source_event_id.is_(None),
                        )
                        .first()
                    ):
                        raise ValueError(
                            "Legacy history must be attributed to exact logs first"
                        )
            # Keep the human public ID; deterministic tie-break for case variants.
            winner = min(
                rows,
                key=lambda p: (p.product_id.lower().startswith("0x"), p.product_id),
            )
            losers = [p for p in rows if p is not winner]
            binding = bindings[0] if bindings else None
            source = next(
                (p for p in rows if binding and p.product_id == binding.product_id),
                None,
            )
            values = scope_values(
                key,
                registry=worker.product_registry_address,
                tracker=worker.shipment_tracker_address,
            )
            if losers or any(getattr(winner, k) != v for k, v in values.items()):
                actions.append((winner, losers, binding, source, values))
        except ValueError as error:
            conflicts.append(
                {
                    "canonical_id": key,
                    "product_ids": [p.product_id for p in rows],
                    "reason": str(error),
                }
            )
    report = {
        "applied": False,
        "changes": [
            {
                "product_id": w.product_id,
                "canonical_id": v["on_chain_product_id"],
                "aliases": [p.product_id for p in losers],
            }
            for w, losers, b, s, v in actions
        ],
        "conflicts": conflicts,
    }
    if not apply:
        return report
    if conflicts:
        raise ReconciliationRequired(
            "Identity conflicts require review; no changes applied"
        )
    for winner, losers, binding, source, values in actions:
        baseline = None
        if (
            binding
            and source is not winner
            and winner.ownership_source == "signed_draft"
            and winner.block_number == 0
        ):
            baseline = {field: getattr(winner, field) for field in PRODUCT_FIELDS}
            for field in ("registered_at", "chain_registered_at"):
                baseline[field] = (
                    baseline[field].isoformat() if baseline[field] else None
                )
        for loser in losers:
            loser.registration_status = "superseded"
            for field in IDENTITY_FIELDS:
                setattr(loser, field, None)
        db.flush()  # Release the unique canonical reservation before assigning it.
        assign_identity(winner, values)
        if source and source is not winner:
            for field in PRODUCT_FIELDS:
                setattr(winner, field, getattr(source, field))
            # Source may have just been archived; the canonical winner is indexed.
            winner.registration_status = (
                "indexed" if winner.chain_registered_at else "unregistered"
            )
        for loser in losers:
            for model in (Checkpoint, CustodyTransfer, Shipment):
                db.query(model).filter_by(product_id=loser.product_id).update(
                    {"product_id": winner.product_id}, synchronize_session="fetch"
                )
            db.query(ProductAlias).filter_by(product_id=loser.product_id).update(
                {"product_id": winner.product_id}, synchronize_session="fetch"
            )
            existing_alias = db.get(ProductAlias, loser.product_id)
            if existing_alias and existing_alias.product_id != winner.product_id:
                raise ReconciliationRequired("Conflicting public alias")
            if not existing_alias:
                db.add(
                    ProductAlias(
                        alias_id=loser.product_id, product_id=winner.product_id
                    )
                )
        if binding:
            binding.product_id = winner.product_id
            if baseline:
                binding.baseline = baseline
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
                    raise ReconciliationRequired(
                        "Chain changed during identity reconciliation"
                    )
            events.extend(batch)
            start = end + 1
        report = reconcile(worker, db, events, apply=args.apply)
        if worker._header(target) != end_hash:
            raise ReconciliationRequired("Chain changed during identity reconciliation")
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "applied": False}))
        raise SystemExit(1)
