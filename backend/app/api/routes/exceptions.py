from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload
from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.limiter import limiter
from app.core.permissions import require_product_owner
from app.models.shipment import Shipment
from app.models.exception import ExceptionPolicy, ShipmentException, ExceptionEvaluation
from app.schemas.exception import (
    PolicyResponse,
    PolicyUpdate,
    Acknowledgement,
    ExceptionResponse,
    ExceptionList,
)
from app.services.identity import require_current_scope
from app.services.exceptions import current_scope, policy_for, pause_reason, writer_lock
from app.services.indexer import IndexerBusy
from app.services.analytics import utc

router = APIRouter()


def health():
    from app.main import indexer_state

    return indexer_state().model_dump()


def lock(db):
    try:
        writer_lock(db)
    except IndexerBusy:
        raise HTTPException(
            409, "Canonical evidence is being updated; retry shortly"
        ) from None


def owned_shipment(db, shipment_id, user):
    shipment = db.query(Shipment).filter_by(shipment_id=shipment_id).first()
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    require_product_owner(shipment.product, user)
    require_current_scope(shipment.product)
    return shipment


@router.get("/", response_model=ExceptionList)
def list_exceptions(
    state: Literal[
        "open", "unacknowledged", "acknowledged", "resolved", "all"
    ] = "open",
    shipment_id: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    scope = current_scope()
    query = (
        db.query(ShipmentException)
        .options(joinedload(ShipmentException.shipment).joinedload(Shipment.product))
        .filter_by(scope=scope)
    )
    if state in {"open", "unacknowledged", "acknowledged"}:
        query = query.filter(ShipmentException.resolved_at.is_(None))
    if state == "resolved":
        query = query.filter(ShipmentException.resolved_at.is_not(None))
    if state == "unacknowledged":
        query = query.filter(ShipmentException.acknowledged_at.is_(None))
    if state == "acknowledged":
        query = query.filter(ShipmentException.acknowledged_at.is_not(None))
    if shipment_id:
        query = query.filter_by(shipment_id=shipment_id)
    previous = db.get(ExceptionEvaluation, scope)
    reason = pause_reason(health())
    if (
        not reason
        and previous
        and utc(previous.evaluated_at) > datetime.now(timezone.utc)
    ):
        reason = "clock_regressed"
    if not reason and (
        not previous
        or (datetime.now(timezone.utc) - utc(previous.evaluated_at)).total_seconds()
        > 180
    ):
        reason = "evaluation_pending" if not previous else "evaluation_stale"
    return dict(
        items=query.order_by(
            ShipmentException.first_observed_at.desc(), ShipmentException.id
        )
        .offset(skip)
        .limit(limit)
        .all(),
        total=query.count(),
        evaluation=dict(
            paused=bool(reason),
            reason=reason,
            evaluated_at=previous.evaluated_at if previous else None,
            block_number=previous.block_number if previous else None,
            uncertain_shipments=previous.uncertain_shipments if previous else 0,
        ),
    )


@router.get("/policies/{shipment_id}", response_model=PolicyResponse)
def get_policy(shipment_id: str, db: Session = Depends(get_db)):
    if not db.query(Shipment).filter_by(shipment_id=shipment_id).first():
        raise HTTPException(404, "Shipment not found")
    return policy_for(db, shipment_id)


@router.put("/policies/{shipment_id}", response_model=PolicyResponse)
@limiter.limit("30/minute")
def update_policy(
    request: Request,
    shipment_id: str,
    body: PolicyUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    lock(db)
    owned_shipment(db, shipment_id, user)
    previous = policy_for(db, shipment_id)
    if body.expected_revision != previous.revision:
        raise HTTPException(409, "Policy changed; reload before saving")
    values = body.model_dump(exclude={"expected_revision"})
    # Identical saves must not invalidate acknowledgements or create new episodes.
    if values == previous.model_dump(include=set(values)):
        return previous
    row = db.get(ExceptionPolicy, shipment_id)
    if row is None:
        row = ExceptionPolicy(shipment_id=shipment_id)
        db.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    row.revision = previous.revision + 1
    row.updated_at, row.updated_by = datetime.now(timezone.utc), user.lower()
    db.commit()
    db.refresh(row)
    return row


@router.post("/{exception_id}/acknowledgement", response_model=ExceptionResponse)
@limiter.limit("30/minute")
def acknowledge(
    request: Request,
    exception_id: str,
    body: Acknowledgement,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    lock(db)
    row = (
        db.query(ShipmentException)
        .filter_by(id=exception_id, scope=current_scope())
        .first()
    )
    if row is None:
        raise HTTPException(404, "Exception not found")
    owned_shipment(db, row.shipment_id, user)
    if row.resolved_at:
        raise HTTPException(
            409, "This occurrence has resolved; reload the exception list"
        )
    if row.acknowledged_at is None:
        row.acknowledged_at, row.acknowledged_by = (
            datetime.now(timezone.utc),
            user.lower(),
        )
        row.acknowledgement_note = body.note.strip() if body.note else None
        db.commit()
        db.refresh(row)
    return row
