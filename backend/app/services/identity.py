"""Canonical scope assignment and stable public/legacy URL resolution."""

from fastapi import HTTPException
from sqlalchemy import or_, func
from web3 import Web3
from app.core.config import settings
from app.core.product_id import canonical_hex
from app.models.product import Product, ProductAlias

IDENTITY_FIELDS = (
    "on_chain_product_id",
    "chain_id",
    "registry_address",
    "tracker_address",
)


def scope_values(public_id, *, chain_id=None, registry=None, tracker=None):
    registry = settings.product_registry_contract if registry is None else registry
    tracker = settings.shipment_tracker_contract if tracker is None else tracker
    chain_id = settings.chain_id if chain_id is None else chain_id
    if (
        not Web3.is_address(registry)
        or not Web3.is_address(tracker)
        or chain_id <= 0
        or int(registry, 16) == 0
        or int(tracker, 16) == 0
    ):
        raise ValueError("An explicit chain, registry and tracker are required")
    return dict(
        on_chain_product_id=canonical_hex(public_id),
        chain_id=chain_id,
        registry_address=registry.lower(),
        tracker_address=tracker.lower(),
    )


def assign_identity(product, values):
    existing = {key: getattr(product, key) for key in IDENTITY_FIELDS}
    if any(value is not None for value in existing.values()) and existing != values:
        raise ValueError("Product identity belongs to a different chain configuration")
    for key, value in values.items():
        setattr(product, key, value)


def require_current_scope(product):
    try:
        expected = scope_values(product.on_chain_product_id or product.product_id)
    except ValueError:
        raise HTTPException(503, "Product chain configuration is unavailable") from None
    if {key: getattr(product, key) for key in IDENTITY_FIELDS} != expected:
        raise HTTPException(
            409, "Product identity needs reconciliation for this environment"
        )


def resolve_product(db, public_id, *, lock=False):
    seen = set()
    for _ in range(32):
        if public_id in seen:
            raise HTTPException(409, "Product alias requires reconciliation")
        seen.add(public_id)
        alias = db.get(ProductAlias, public_id)
        if alias:
            public_id = alias.product_id
            continue
        query = db.query(Product).filter_by(product_id=public_id)
        if lock:
            query = query.with_for_update()
        product = query.first()
        if product and product.registration_status == "superseded":
            raise HTTPException(409, "Product alias requires reconciliation")
        return product
    raise HTTPException(409, "Product alias requires reconciliation")


def find_canonical_product(db, key, chain_id, registry):
    # Persisted identity wins; a display/hex fallback is for unreconciled records
    # only, and any conflicting claimant is rejected rather than silently merged.
    encoded = canonical_hex(key)
    raw = bytes.fromhex(encoded[2:])
    candidates = [encoded]
    try:
        display = raw.rstrip(b"\x00").decode("utf-8")
        if display and canonical_hex(display) == encoded:
            candidates.append(display)
    except (UnicodeError, ValueError):
        pass
    matches = (
        db.query(Product)
        .filter(
            Product.registration_status != "superseded",
            or_(
                (Product.chain_id == chain_id)
                & (Product.registry_address == registry.lower())
                & (Product.on_chain_product_id == encoded),
                Product.product_id.in_(candidates),
                func.lower(Product.product_id) == encoded,
            ),
        )
        .with_for_update()
        .all()
    )
    if len(matches) > 1:
        raise ValueError("Conflicting product identities require reconciliation")
    return matches[0] if matches else None
