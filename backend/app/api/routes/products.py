import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError
from web3 import Web3
from app.core.auth import get_current_user
from app.core.permissions import require_product_owner, require_editable_draft
from typing import List, Optional

from app.core.database import get_db
from app.core.limiter import limiter
from app.core.config import settings
from app.models.product import Product
from app.models.shipment import Checkpoint, CustodyTransfer
from app.schemas.product import (
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)
from app.schemas.shipment import CheckpointResponse, CustodyTransferResponse
from app.services.events import broadcaster
from app.services.registration import evidence, reconcile, observe
from app.models.registration import RegistrationAttempt
from app.models.chain import ChainEvent
from app.schemas.product import (
    RegistrationSubmission,
    RegistrationAttemptResponse,
    RegistrationLifecycleResponse,
    MetadataHistoryResponse,
)
from app.services.identity import (
    resolve_product,
    scope_values,
    require_current_scope,
    find_canonical_product,
)
from app.models.chain import IndexerCursor
from app.schemas.product import VerificationResponse

router = APIRouter()


PRODUCT_SORT_COLUMNS = {
    "name": Product.name,
    "product_id": Product.product_id,
    "registered_at": Product.chain_registered_at,
    "created_at": Product.created_at,
}


@router.get("/", response_model=ProductListResponse)
def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    search: Optional[str] = Query(default=None),
    sort_by: Optional[str] = Query(default=None),
    sort_order: Optional[str] = Query(default="asc"),
    db: Session = Depends(get_db),
):
    """List all registered products with optional search, sorting, and pagination."""
    query = (
        db.query(Product)
        .options(selectinload(Product.shipments))
        .filter(Product.registration_status != "superseded")
    )
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    total = query.count()
    col = PRODUCT_SORT_COLUMNS.get(sort_by or "", Product.created_at)
    order = col.desc() if sort_order == "desc" else col.asc()
    items = query.order_by(order).offset(skip).limit(limit).all()
    return {"items": items, "total": total}


@router.post("/", response_model=ProductResponse)
@limiter.limit("30/minute")
async def create_product(
    request: Request,
    product_in: ProductCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Create a new product."""
    if (
        product_in.manufacturer_address
        and product_in.manufacturer_address.lower() != current_user
    ):
        raise HTTPException(
            status_code=403, detail="Manufacturer must match the signed-in wallet"
        )
    for _ in range(5):
        public_id = f"PROD-{uuid.uuid4().hex[:8].upper()}"
        try:
            identity = scope_values(public_id)
        except ValueError:
            raise HTTPException(
                503, "Explicit product chain configuration is required"
            ) from None
        try:
            if find_canonical_product(
                db,
                identity["on_chain_product_id"],
                settings.chain_id,
                settings.product_registry_contract,
            ):
                continue
        except ValueError:
            continue
        now = datetime.now(timezone.utc)
        product = Product(
            product_id=public_id,
            name=product_in.name,
            description=product_in.description,
            metadata_uri=product_in.metadata_uri,
            manufacturer_address=Web3.to_checksum_address(current_user),
            owner_address=current_user,
            ownership_source="signed_draft",
            registration_status="draft",
            created_at=now,
            registered_at=now,
            chain_registered_at=None,
            block_number=0,
            tx_hash="0x",
            **identity,
        )
        try:
            with db.begin_nested():
                db.add(product)
                db.flush()
            break
        except IntegrityError:
            # Display and canonical identity reservations both survive a race.
            # A bounded retry allocates a fresh ID; never reuse an existing row.
            continue
    else:
        raise HTTPException(409, "Could not allocate a unique product ID; please retry")
    db.commit()
    db.refresh(product)
    await broadcaster.broadcast(
        "product_created",
        {"product_id": product.product_id, "name": product.name},
    )
    return product


@router.put("/{product_id}", response_model=ProductResponse)
@limiter.limit("30/minute")
def update_product(
    request: Request,
    product_id: str,
    product_in: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Update an existing product."""
    product = resolve_product(db, product_id, lock=True)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    require_editable_draft(product, current_user)
    require_current_scope(product)
    if (
        db.query(RegistrationAttempt)
        .filter(
            RegistrationAttempt.product_id == product.product_id,
            RegistrationAttempt.status.in_(["submitted", "confirming", "indexing"]),
        )
        .first()
    ):
        raise HTTPException(
            409, "Resolve the pending registration before editing the draft"
        )
    update_data = product_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return product


@router.get("/{product_id}", response_model=dict)
def get_product(product_id: str, db: Session = Depends(get_db)):
    """Get a single product by its product_id, including history and custody transfers."""
    product = resolve_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product_id = product.product_id
    history = (
        db.query(Checkpoint)
        .filter(Checkpoint.product_id == product_id)
        .order_by(Checkpoint.timestamp.asc())
        .all()
    )
    transfers = (
        db.query(CustodyTransfer)
        .filter(CustodyTransfer.product_id == product_id)
        .order_by(CustodyTransfer.timestamp.asc())
        .all()
    )

    return {
        "product": ProductResponse.model_validate(product),
        "history": [CheckpointResponse.model_validate(cp) for cp in history],
        "transfers": [CustodyTransferResponse.model_validate(ct) for ct in transfers],
    }


@router.get("/{product_id}/verify", response_model=VerificationResponse)
def verify_product(product_id: str, db: Session = Depends(get_db)):
    """Return verification status for a product."""
    product = resolve_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product_id = product.product_id
    checkpoint_count = (
        db.query(Checkpoint).filter(Checkpoint.product_id == product_id).count()
    )
    is_delivered = (
        db.query(Checkpoint)
        .filter(Checkpoint.product_id == product_id, Checkpoint.status == "3")
        .first()
        is not None
    )

    from app.main import indexer_state

    sync_health = indexer_state()
    registration_evidence = evidence(db, product)
    binding = product.indexed_state
    cursor = db.get(IndexerCursor, binding.scope) if binding else None
    return {
        "product_id": product_id,
        "is_registered": registration_evidence["status"] == "verified",
        "evidence": registration_evidence,
        "is_delivered": is_delivered,
        "checkpoint_count": checkpoint_count,
        "synchronization": {
            "status": sync_health.status,
            "reason": sync_health.reason,
            "lag_blocks": sync_health.lag_blocks,
            "confirmation_policy": "depth",
            "confirmations": settings.indexer_confirmations,
            "cursor_storage": "database",
            "indexer_enabled": settings.indexer_enabled,
            "indexed_block": cursor.last_processed_block if cursor else None,
            "last_successful_sync": cursor.updated_at if cursor else None,
        },
    }


@router.post("/{product_id}/registration", response_model=RegistrationAttemptResponse)
@limiter.limit("30/minute")
def submit_registration(
    request: Request,
    product_id: str,
    submission: RegistrationSubmission,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    product = resolve_product(db, product_id, lock=True)
    if not product:
        raise HTTPException(404, "Product not found")
    require_product_owner(product, current_user)
    require_current_scope(product)
    tx_hash = submission.tx_hash.lower()
    existing = (
        db.query(RegistrationAttempt)
        .filter_by(chain_id=product.chain_id, tx_hash=tx_hash)
        .first()
    )
    if existing:
        if (
            existing.product_id != product.product_id
            or existing.operation != submission.operation
            or existing.metadata_uri != submission.metadata_uri
        ):
            raise HTTPException(
                409, "Transaction is already associated with another submission"
            )
        return existing
    if (
        submission.operation == "registration"
        and product.registration_status not in {"draft", "unregistered"}
        and not (
            product.registration_status == "indexed"
            and product.tx_hash.lower() == tx_hash
        )
    ):
        raise HTTPException(
            409, "Product is already indexed or requires identity reconciliation"
        )
    if submission.operation == "metadata" and (
        product.registration_status != "indexed" or submission.metadata_uri is None
    ):
        raise HTTPException(
            409, "Metadata updates require an indexed product and the requested URI"
        )
    if (
        db.query(RegistrationAttempt).filter_by(product_id=product.product_id).count()
        >= 100
    ):
        raise HTTPException(
            409, "Submission history limit reached; operator review required"
        )
    payload_snapshot = {
        "name": product.name,
        "description": product.description or "",
        "metadataURI": product.metadata_uri or "",
    }
    if product.registration_status == "indexed" and product.indexed_state:
        original = (
            db.query(ChainEvent)
            .filter_by(
                scope=product.indexed_state.scope,
                product_key=product.on_chain_product_id,
                canonical=True,
                event_type="ProductRegistered",
            )
            .first()
        )
        if original:
            payload_snapshot = dict(
                name=original.payload["name"], **original.payload["_registration"]
            )
    attempt = RegistrationAttempt(
        product_id=product.product_id,
        chain_id=product.chain_id,
        registry_address=product.registry_address,
        submitted_by=current_user,
        tx_hash=tx_hash,
        registration_payload=payload_snapshot,
        operation=submission.operation,
        metadata_uri=submission.metadata_uri,
        status="submitted",
        reason="awaiting_receipt",
        created_at=datetime.now(timezone.utc),
    )
    if submission.replaces_tx_hash:
        old = (
            db.query(RegistrationAttempt)
            .filter_by(
                product_id=product.product_id,
                chain_id=product.chain_id,
                tx_hash=submission.replaces_tx_hash.lower(),
            )
            .first()
        )
        if (
            not old
            or old.replaced_by
            or old.operation != submission.operation
            or old.status == "indexed"
            or old.tx_hash == tx_hash
        ):
            raise HTTPException(409, "Invalid replacement reference")
        attempt.replaces_tx_hash = old.tx_hash
        try:
            previous = observe(product, old)
            replacement = observe(product, attempt)
        except Exception:
            raise HTTPException(
                503, "Replacement evidence is temporarily unavailable"
            ) from None
        if previous["nonce"] is None and old.nonce is not None:
            previous["nonce"] = old.nonce
        if (
            previous["nonce"] is None
            or previous["nonce"] != replacement["nonce"]
            or (
                replacement["status"] == "failed"
                and replacement["reason"] != "transaction_cancelled"
            )
        ):
            raise HTTPException(
                409,
                "Replacement must match the original sender, nonce and product operation",
            )
        attempt.replaces_tx_hash = old.tx_hash
        old.replaced_by, old.status, old.reason = (
            tx_hash,
            "replaced",
            "transaction_replaced",
        )
    db.add(attempt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "Concurrent submission; refresh registration history"
        ) from None
    db.refresh(attempt)
    return attempt


@router.get("/{product_id}/registration", response_model=RegistrationLifecycleResponse)
def registration_history(product_id: str, db: Session = Depends(get_db)):
    product = resolve_product(db, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    return {
        "product_id": product.product_id,
        "attempts": db.query(RegistrationAttempt)
        .filter_by(product_id=product.product_id)
        .order_by(RegistrationAttempt.id.desc())
        .limit(100)
        .all(),
    }


@router.post(
    "/{product_id}/registration/reconcile", response_model=RegistrationAttemptResponse
)
@limiter.limit("10/minute")
def reconcile_registration(
    request: Request,
    product_id: str,
    tx_hash: str = Query(pattern=r"^0x[0-9a-fA-F]{64}$"),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    product = resolve_product(db, product_id, lock=True)
    if not product:
        raise HTTPException(404, "Product not found")
    require_product_owner(product, current_user)
    require_current_scope(product)
    attempt = (
        db.query(RegistrationAttempt)
        .filter_by(product_id=product.product_id, tx_hash=tx_hash.lower())
        .first()
    )
    if not attempt:
        raise HTTPException(404, "Submission not found")
    reconcile(db, product, attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


@router.get("/{product_id}/metadata-history", response_model=MetadataHistoryResponse)
def metadata_history(product_id: str, db: Session = Depends(get_db)):
    product = resolve_product(db, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    binding = product.indexed_state
    rows = (
        []
        if not binding
        else db.query(ChainEvent)
        .filter(
            ChainEvent.scope == binding.scope,
            ChainEvent.product_key == product.on_chain_product_id,
            ChainEvent.event_type.in_(["ProductRegistered", "ProductMetadataUpdated"]),
        )
        .order_by(
            ChainEvent.block_number.desc(),
            ChainEvent.transaction_index.desc(),
            ChainEvent.log_index.desc(),
        )
        .limit(100)
        .all()
    )
    return {
        "product_id": product.product_id,
        "items": [
            dict(
                transaction_hash=row.transaction_hash,
                block_number=row.block_number,
                block_hash=row.block_hash,
                log_index=row.log_index,
                metadata_uri=(
                    row.payload.get("_registration", {}).get("metadataURI")
                    if row.event_type == "ProductRegistered"
                    else row.payload.get("metadataURI")
                ),
                canonical=row.canonical,
            )
            for row in rows
        ],
    }
