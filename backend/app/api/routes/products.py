import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.limiter import limiter
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

router = APIRouter()


PRODUCT_SORT_COLUMNS = {
    "name": Product.name,
    "product_id": Product.product_id,
    "registered_at": Product.registered_at,
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
    query = db.query(Product)
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    total = query.count()
    col = PRODUCT_SORT_COLUMNS.get(sort_by or "", Product.registered_at)
    order = col.desc() if sort_order == "desc" else col.asc()
    items = query.order_by(order).offset(skip).limit(limit).all()
    return {"items": items, "total": total}


@router.post("/", response_model=ProductResponse)
@limiter.limit("30/minute")
async def create_product(
    request: Request,
    product_in: ProductCreate,
    db: Session = Depends(get_db),
):
    """Create a new product."""
    product = Product(
        product_id=f"PROD-{uuid.uuid4().hex[:8].upper()}",
        name=product_in.name,
        description=product_in.description,
        metadata_uri=product_in.metadata_uri,
        manufacturer_address=product_in.manufacturer_address,
        registered_at=datetime.now(timezone.utc),
        block_number=0,
        tx_hash="0x",
    )
    db.add(product)
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
):
    """Update an existing product."""
    product = db.query(Product).filter(Product.product_id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = product_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return product


@router.get("/{product_id}", response_model=dict)
def get_product(product_id: str, db: Session = Depends(get_db)):
    """Get a single product by its product_id, including history and custody transfers."""
    product = db.query(Product).filter(Product.product_id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    history = db.query(Checkpoint).filter(Checkpoint.product_id == product_id).order_by(Checkpoint.timestamp.asc()).all()
    transfers = db.query(CustodyTransfer).filter(CustodyTransfer.product_id == product_id).order_by(CustodyTransfer.timestamp.asc()).all()

    return {
        "product": ProductResponse.model_validate(product),
        "history": [CheckpointResponse.model_validate(cp) for cp in history],
        "transfers": [CustodyTransferResponse.model_validate(ct) for ct in transfers],
    }


@router.get("/{product_id}/verify", response_model=dict)
def verify_product(product_id: str, db: Session = Depends(get_db)):
    """Return verification status for a product."""
    product = db.query(Product).filter(Product.product_id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    checkpoint_count = db.query(Checkpoint).filter(Checkpoint.product_id == product_id).count()
    is_delivered = (
        db.query(Checkpoint)
        .filter(Checkpoint.product_id == product_id, Checkpoint.status == "3")
        .first()
        is not None
    )

    try:
        registered = verify_registration(product)
    except Exception:
        raise HTTPException(status_code=503, detail="Registration evidence is temporarily unavailable")
    return {
        "product_id": product_id,
        "is_registered": registered,
        "is_delivered": is_delivered,
        "checkpoint_count": checkpoint_count,
    }
