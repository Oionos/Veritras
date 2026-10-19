"""Public evidence comes only from the bound product's canonical journal."""

from datetime import datetime, timezone
from app.models.chain import ChainEvent


def product_timeline(db, product, skip, limit):
    binding = product.indexed_state
    query = db.query(ChainEvent).filter(
        ChainEvent.scope == (binding.scope if binding else ""),
        ChainEvent.product_key == product.on_chain_product_id,
        ChainEvent.chain_id == product.chain_id,
        ChainEvent.contract_address.in_(
            [product.registry_address, product.tracker_address]
        ),
        ChainEvent.canonical.is_(True),
        ChainEvent.event_type.in_(
            [
                "ProductRegistered",
                "ProductMetadataUpdated",
                "CheckpointRecorded",
                "CustodyTransferred",
                "DeliveryCompleted",
            ]
        ),
    )
    total = query.count() if binding else 0
    rows = (
        query.order_by(
            ChainEvent.block_number,
            ChainEvent.transaction_index,
            ChainEvent.log_index,
        )
        .offset(skip)
        .limit(limit)
        .all()
        if binding
        else []
    )
    items = []
    for row in rows:
        args = row.payload
        items.append(
            dict(
                event_id=row.event_id,
                event_type=row.event_type,
                timestamp=(
                    datetime.fromtimestamp(args["timestamp"], timezone.utc)
                    if args.get("timestamp") is not None
                    else None
                ),
                block_number=row.block_number,
                block_hash=row.block_hash,
                transaction_hash=row.transaction_hash,
                transaction_index=row.transaction_index,
                log_index=row.log_index,
                contract_address=row.contract_address,
                location=args.get("location"),
                status=str(args["status"]) if "status" in args else None,
                handler=args.get("handler"),
                from_address=args.get("from"),
                to_address=args.get("to"),
                notes=args.get("notes"),
                metadata_uri=(
                    args.get("_registration", {}).get("metadataURI")
                    if row.event_type == "ProductRegistered"
                    else args.get("metadataURI")
                ),
            )
        )
    return dict(
        product_id=product.product_id,
        chain_id=product.chain_id,
        items=items,
        total=total,
        skip=skip,
        limit=limit,
    )
