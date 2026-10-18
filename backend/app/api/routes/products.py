import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError
from web3 import Web3
from app.core.auth import get_current_user
from app.core.permissions import require_editable_draft
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
from app.services.verification import verify_registration
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

    try:
        registered = verify_registration(product)
    except Exception:
        raise HTTPException(
            status_code=503, detail="Registration evidence is temporarily unavailable"
        )
    binding = product.indexed_state
    cursor = db.get(IndexerCursor, binding.scope) if binding else None
    return {
        "product_id": product_id,
        "is_registered": registered,
        "is_delivered": is_delivered,
        "checkpoint_count": checkpoint_count,
        "synchronization": {
            "confirmation_policy": "depth",
            "confirmations": settings.indexer_confirmations,
            "cursor_storage": "database",
            "indexer_enabled": settings.indexer_enabled,
            "indexed_block": cursor.last_processed_block if cursor else None,
            "last_successful_sync": cursor.updated_at if cursor else None,
        },
    }
