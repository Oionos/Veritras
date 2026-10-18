import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from app.core.limiter import limiter
from sqlalchemy.orm import Session, joinedload
from app.core.auth import get_current_user
from app.core.permissions import require_product_owner
from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from app.core.database import get_db
from app.models.product import Product
from app.models.shipment import Checkpoint, CustodyTransfer, Shipment
from app.schemas.shipment import (
    CheckpointResponse,
    CustodyTransferResponse,
    ShipmentCreate,
    ShipmentListResponse,
    ShipmentResponse,
    ShipmentUpdate,
)
from app.services.analytics import hydrate_lifecycle, utc
from app.services.events import broadcaster
from app.services.identity import resolve_product, require_current_scope

router = APIRouter()


SHIPMENT_SORT_COLUMNS = {
    "origin": Shipment.origin,
    "destination": Shipment.destination,
    "status": Shipment.status,
    "created_at": Shipment.created_at,
}


@router.get("/", response_model=ShipmentListResponse)
def get_all_shipments(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    sort_by: Optional[str] = Query(default=None),
    sort_order: Optional[str] = Query(default="desc"),
    db: Session = Depends(get_db),
):
    """List all shipments with optional status filter, search, sorting, and pagination."""
    query = db.query(Shipment).options(joinedload(Shipment.product))
    if status is not None:
        query = query.filter(Shipment.status == status)
    if search:
        query = query.filter(
            or_(
                Shipment.origin.ilike(f"%{search}%"),
                Shipment.destination.ilike(f"%{search}%"),
            )
        )
    total = query.count()
    col = SHIPMENT_SORT_COLUMNS.get(sort_by or "", Shipment.created_at)
    order = col.asc() if sort_order == "asc" else col.desc()
    items = query.order_by(order).offset(skip).limit(limit).all()
    hydrate_lifecycle(db, items)
    return {"items": items, "total": total}


@router.post("/", response_model=ShipmentResponse)
@limiter.limit("30/minute")
async def create_shipment(
    request: Request,
    shipment_in: ShipmentCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Create a new shipment."""
    product = resolve_product(db, shipment_in.product_id, lock=True)
    if not product:
        raise HTTPException(status_code=422, detail="Product not found")
    require_product_owner(product, current_user)
    require_current_scope(product)
    if db.query(Shipment).filter_by(product_id=product.product_id).first():
        raise HTTPException(409, "This item already has a shipment lifecycle")

    shipment = Shipment(
        shipment_id=f"SHIP-{uuid.uuid4().hex[:8].upper()}",
        product_id=product.product_id,
        origin=shipment_in.origin,
        destination=shipment_in.destination,
        status=product.indexed_state.status if product.indexed_state else "0",
        notes=shipment_in.notes,
        expected_arrival_at=shipment_in.expected_arrival_at,
        expected_arrival_recorded_at=(
            datetime.now(timezone.utc) if shipment_in.expected_arrival_at else None
        ),
    )
    db.add(shipment)
    try:
        db.flush()
        hydrate_lifecycle(db, [shipment])
        if shipment.expected_arrival_at and (
            shipment.departed_at or shipment.delivered_at
        ):
            raise HTTPException(
                409, "Expected arrival must be planned before indexed departure"
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.query(Shipment).filter_by(product_id=product.product_id).first():
            raise HTTPException(409, "This item already has a shipment lifecycle")
        raise HTTPException(
            status_code=409, detail="Shipment ID conflict, please retry"
        )
    db.refresh(shipment)
    await broadcaster.broadcast(
        "shipment_created",
        {"shipment_id": shipment.shipment_id, "product_id": shipment.product_id},
    )
    hydrate_lifecycle(db, [shipment])
    return shipment


@router.put("/{shipment_id}", response_model=ShipmentResponse)
@limiter.limit("30/minute")
def update_shipment(
    request: Request,
    shipment_id: str,
    shipment_in: ShipmentUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Update an existing shipment."""
    shipment = db.query(Shipment).filter(Shipment.shipment_id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    product = (
        db.query(Product)
        .filter(Product.product_id == shipment.product_id)
        .with_for_update()
        .first()
    )
    if not product:
        raise HTTPException(
            status_code=409, detail="Shipment product needs reconciliation"
        )
    require_product_owner(product, current_user)

    require_current_scope(product)
    update_data = shipment_in.model_dump(exclude_unset=True)
    hydrate_lifecycle(db, [shipment])
    if "expected_arrival_at" in update_data and (
        shipment.departed_at or shipment.delivered_at
    ):
        raise HTTPException(409, "Expected arrival is locked after indexed departure")
    if "expected_arrival_at" in update_data and utc(
        update_data["expected_arrival_at"]
    ) != utc(shipment.expected_arrival_at):
        shipment.expected_arrival_recorded_at = (
            datetime.now(timezone.utc) if update_data["expected_arrival_at"] else None
        )
    for field, value in update_data.items():
        setattr(shipment, field, value)

    db.commit()
    db.refresh(shipment)
    hydrate_lifecycle(db, [shipment])
    return shipment


@router.get("/{product_id}/history", response_model=List[CheckpointResponse])
def get_checkpoint_history(product_id: str, db: Session = Depends(get_db)):
    """Get checkpoint history for a given product."""
    product = resolve_product(db, product_id)
    product_id = product.product_id if product else product_id
    return (
        db.query(Checkpoint)
        .filter(Checkpoint.product_id == product_id)
        .order_by(Checkpoint.timestamp.asc())
        .all()
    )


@router.get("/{product_id}/transfers", response_model=List[CustodyTransferResponse])
def get_custody_transfers(product_id: str, db: Session = Depends(get_db)):
    """Get custody transfer history for a given product."""
    product = resolve_product(db, product_id)
    product_id = product.product_id if product else product_id
    return (
        db.query(CustodyTransfer)
        .filter(CustodyTransfer.product_id == product_id)
        .order_by(CustodyTransfer.timestamp.asc())
        .all()
    )
