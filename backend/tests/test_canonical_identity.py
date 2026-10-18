"""Canonical reservations, aliases and safe reconciliation across both databases."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.core.product_id import canonical_hex
from app.models.product import Product, ProductAlias
from app.models.shipment import Shipment, Checkpoint
from app.models.chain import IndexedProduct
from app.services.identity import scope_values, resolve_product, assign_identity
from app.services.indexer import ReconciliationRequired
from manage_identity import reconcile
from tests.test_indexer import stack, OWNER


def legacy_draft(db, **kwargs):
    product = Product(
        product_id="PROD-TEST",
        name="Widget",
        manufacturer_address=OWNER,
        owner_address=OWNER,
        ownership_source="signed_draft",
        registered_at=datetime(2026, 1, 1),
        created_at=datetime(2026, 1, 1),
        registration_status="draft",
        block_number=0,
        tx_hash="0x",
        **kwargs,
    )
    db.add(product)
    db.commit()
    return product


def test_new_draft_reserves_identity_without_registration(client_fixture):
    product = client_fixture.post("/products/", json={"name": "New item"}).json()
    assert product["on_chain_product_id"] == canonical_hex(product["product_id"])
    assert (
        product["chain_id"] == settings.chain_id
        and product["registration_status"] == "draft"
    )
    assert product["created_at"] and product["registered_at"] is None
    first = client_fixture.post(
        "/shipments/",
        json={"product_id": product["product_id"], "origin": "A", "destination": "B"},
    )
    assert first.status_code == 200
    assert first.json()["on_chain_product_id"] == product["on_chain_product_id"]
    assert first.json()["tracker_address"] == product["tracker_address"]
    assert (
        client_fixture.post(
            "/shipments/",
            json={
                "product_id": product["product_id"],
                "origin": "C",
                "destination": "D",
            },
        ).status_code
        == 409
    )


def test_scope_cannot_change_when_environment_changes(client_fixture, monkeypatch):
    product = client_fixture.post("/products/", json={"name": "New item"}).json()
    monkeypatch.setattr(settings, "shipment_tracker_contract", "0x" + "3" * 40)
    assert (
        client_fixture.put(
            "/products/" + product["product_id"], json={"name": "Other"}
        ).status_code
        == 409
    )
    assert (
        client_fixture.post(
            "/shipments/",
            json={
                "product_id": product["product_id"],
                "origin": "A",
                "destination": "B",
            },
        ).status_code
        == 409
    )


def test_id_collision_retries_without_reusing_product(client_fixture):
    fixed, fresh = SimpleNamespace(hex="a" * 32), SimpleNamespace(hex="b" * 32)
    with patch("app.api.routes.products.uuid.uuid4", return_value=fixed):
        first = client_fixture.post("/products/", json={"name": "Original"}).json()
    with patch("app.api.routes.products.uuid.uuid4", side_effect=[fixed, fresh]):
        second = client_fixture.post("/products/", json={"name": "Second"}).json()
    assert second["product_id"] != first["product_id"]
    with patch("app.api.routes.products.uuid.uuid4", return_value=fixed):
        assert (
            client_fixture.post("/products/", json={"name": "Collision"}).status_code
            == 409
        )
    assert (
        client_fixture.get("/products/" + first["product_id"]).json()["product"]["name"]
        == "Original"
    )


def test_reconciliation_preserves_urls_draft_and_reorg(stack):
    worker = stack.new()
    worker.poll_once()
    with stack.sessions() as db:
        draft = legacy_draft(db)
        db.add(
            Shipment(
                shipment_id="SHIP-OLD",
                product_id=canonical_hex("PROD-TEST"),
                origin="A",
                destination="B",
            )
        )
        db.commit()
        before = reconcile(worker, db, stack.chain.events)
        assert before["changes"][0]["aliases"] == [canonical_hex("PROD-TEST")]
        assert db.get(ProductAlias, canonical_hex("PROD-TEST")) is None
        assert draft.on_chain_product_id is None
        result = reconcile(worker, db, stack.chain.events, apply=True)
        db.commit()
        db.expire_all()
        assert result["applied"]
        winner = resolve_product(db, canonical_hex("PROD-TEST"))
        assert (
            winner.product_id == "PROD-TEST" and winner.registration_status == "indexed"
        )
        assert winner.chain_registered_at and winner.owner_address == OWNER
        assert db.query(Shipment).one().product_id == winner.product_id
        assert db.query(IndexedProduct).one().product_id == winner.product_id
        assert (
            db.query(Product).filter_by(registration_status="superseded").count() == 1
        )
        assert reconcile(worker, db, stack.chain.events, apply=True)["changes"] == []
    from tests.test_indexer import h

    stack.chain.hashes.update({n: h(n + 1000) for n in range(1, 6)})
    stack.chain.events = []
    stack.new().poll_once()
    with stack.sessions() as db:
        winner = resolve_product(db, canonical_hex("PROD-TEST"))
        assert winner.registration_status == "draft" and winner.owner_address == OWNER
        assert winner.chain_registered_at is None
        assert winner.on_chain_product_id == canonical_hex("PROD-TEST")


@pytest.mark.parametrize(
    "conflict", ["manufacturer", "shipment", "history", "transaction", "no_evidence"]
)
def test_reconciliation_conflicts_are_atomic(stack, conflict):
    worker = stack.new()
    worker.poll_once()
    with stack.sessions() as db:
        draft = legacy_draft(db)
        if conflict == "manufacturer":
            draft.manufacturer_address = "0x" + "9" * 40
        if conflict == "transaction":
            draft.block_number, draft.tx_hash = 99, "0x" + "a" * 64
        if conflict == "shipment":
            for index, pid in enumerate(["PROD-TEST", canonical_hex("PROD-TEST")]):
                db.add(
                    Shipment(
                        shipment_id=f"SHIP-{index}",
                        product_id=pid,
                        origin="A",
                        destination="B",
                    )
                )
        if conflict == "history":
            db.add(
                Checkpoint(
                    product_id="PROD-TEST",
                    location="Untrusted",
                    status="0",
                    handler_address=OWNER,
                    timestamp=datetime.now(),
                    block_number=2,
                    tx_hash="0x",
                )
            )
        db.commit()
        events = [] if conflict == "no_evidence" else stack.chain.events
        assert reconcile(worker, db, events)["conflicts"]
        with pytest.raises(ReconciliationRequired):
            reconcile(worker, db, events, apply=True)
        db.rollback()
        assert db.query(ProductAlias).count() == 0
        assert (
            db.query(Product).filter_by(registration_status="superseded").count() == 0
        )


def test_unknown_legacy_never_gets_ownership_or_registration(stack):
    with stack.sessions() as db:
        p = legacy_draft(db)
        p.ownership_source = p.owner_address = None
        p.registration_status = "legacy_unreconciled"
        db.commit()
        assert reconcile(stack.new(), db, [], apply=True)["changes"] == []
        assert p.on_chain_product_id is None and p.owner_address is None


def test_canonical_and_shipment_constraints_reject_races(stack):
    with stack.sessions() as db:
        p = legacy_draft(db, **scope_values("PROD-TEST"))
        with pytest.raises(ValueError):
            assign_identity(p, scope_values("PROD-TEST", chain_id=1))
        db.add(
            Product(
                product_id=canonical_hex("PROD-TEST"),
                name="Twin",
                manufacturer_address=OWNER,
                registered_at=datetime.now(),
                block_number=0,
                tx_hash="0x",
                **scope_values("PROD-TEST"),
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(
            Shipment(
                shipment_id="SHIP-1",
                product_id=p.product_id,
                origin="A",
                destination="B",
            )
        )
        db.commit()
        db.add(
            Shipment(
                shipment_id="SHIP-2",
                product_id=p.product_id,
                origin="C",
                destination="D",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_alias_routes_authorize_and_update_the_canonical_product(
    client_fixture, db_session
):
    product = client_fixture.post("/products/", json={"name": "Current"}).json()
    db_session.add(
        ProductAlias(alias_id="OLD-PUBLIC-ID", product_id=product["product_id"])
    )
    db_session.commit()
    assert (
        client_fixture.get("/products/OLD-PUBLIC-ID").json()["product"]["product_id"]
        == product["product_id"]
    )
    assert (
        client_fixture.put("/products/OLD-PUBLIC-ID", json={"name": "Updated"}).json()[
            "name"
        ]
        == "Updated"
    )
    assert (
        client_fixture.get("/products/OLD-PUBLIC-ID/verify").json()["is_registered"]
        is False
    )
    assert (
        client_fixture.post(
            "/shipments/",
            json={"product_id": "OLD-PUBLIC-ID", "origin": "A", "destination": "B"},
        ).json()["product_id"]
        == product["product_id"]
    )
    assert (
        client_fixture.post(
            "/shipments/",
            json={
                "product_id": product["product_id"],
                "origin": "C",
                "destination": "D",
            },
        ).status_code
        == 409
    )


def test_id_allocator_does_not_shadow_an_unscoped_hex_legacy_row(
    client_fixture, db_session
):
    old_id = "PROD-AAAAAAAA"
    db_session.add(
        Product(
            product_id=canonical_hex(old_id),
            name="Legacy",
            manufacturer_address=OWNER,
            registered_at=datetime.now(),
            block_number=0,
            tx_hash="0x",
        )
    )
    db_session.commit()
    with patch(
        "app.api.routes.products.uuid.uuid4",
        side_effect=[SimpleNamespace(hex="a" * 32), SimpleNamespace(hex="b" * 32)],
    ):
        created = client_fixture.post("/products/", json={"name": "Fresh"}).json()
    assert created["product_id"] == "PROD-BBBBBBBB"
