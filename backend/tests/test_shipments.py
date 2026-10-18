import pytest

from app.services.identity import scope_values
from app.models.product import Product
from app.models.shipment import Checkpoint, CustodyTransfer, Shipment
from app.schemas.shipment import (
    CheckpointResponse,
    CustodyTransferResponse,
    ShipmentListResponse,
    ShipmentResponse,
)
from datetime import datetime, timezone


@pytest.fixture(scope="function")
def seeded_db(db_session):
    product = Product(
        product_id="0x" + "b" * 64,
        name="Shipment Test Product",
        description="For shipment tests",
        metadata_uri="ipfs://shipment",
        manufacturer_address="0x1234567890123456789012345678901234567890",
        owner_address="0x1234567890123456789012345678901234567890",
        ownership_source="chain_event",
        **scope_values("0x" + "b" * 64),
        registration_status="draft",
        created_at=datetime.now(timezone.utc),
        registered_at=datetime.now(timezone.utc),
        block_number=200,
        tx_hash="0xshipmenttx",
    )
    db_session.add(product)
    db_session.add(Product(product_id="0x"+"c"*64, name="Second item", manufacturer_address=product.manufacturer_address, owner_address=product.owner_address, ownership_source=product.ownership_source, registered_at=product.registered_at, block_number=0, tx_hash="0x", **scope_values("0x"+"c"*64)))
    db_session.commit()

    cp1 = Checkpoint(
        product_id=product.product_id,
        location="Origin",
        status="0",
        handler_address="0xhandler1",
        notes=None,
        timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        block_number=201,
        tx_hash="0xcp1",
    )
    cp2 = Checkpoint(
        product_id=product.product_id,
        location="Midpoint",
        status="1",
        handler_address="0xhandler2",
        notes="In transit",
        timestamp=datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc),
        block_number=202,
        tx_hash="0xcp2",
    )
    db_session.add_all([cp1, cp2])

    transfer = CustodyTransfer(
        product_id=product.product_id,
        from_address="0xhandler1",
        to_address="0xhandler2",
        timestamp=datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc),
        block_number=203,
        tx_hash="0xtransfer1",
    )
    db_session.add(transfer)
    db_session.commit()
    return db_session


def test_post_shipment_creates_shipment_successfully(client_fixture, seeded_db):
    """Regression test: POST /shipments must not return 405 Method Not Allowed."""
    payload = {
        "product_id": "0x" + "b" * 64,
        "origin": "Origin Warehouse",
        "destination": "Destination Warehouse",
        "status": "0",
        "notes": "Fragile items",
    }
    response = client_fixture.post("/shipments", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["product_id"] == payload["product_id"]
    assert data["origin"] == payload["origin"]
    assert data["destination"] == payload["destination"]
    assert data["status"] == payload["status"]
    assert data["notes"] == payload["notes"]
    assert data["block_number"] == 0
    assert data["tx_hash"] == "0x"


def test_post_shipment_returns_created_shipment_with_generated_id(client_fixture, seeded_db):
    payload = {
        "product_id": "0x" + "b" * 64,
        "origin": "Origin",
        "destination": "Destination",
        "status": "0",
    }
    response = client_fixture.post("/shipments", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "shipment_id" in data
    assert data["shipment_id"].startswith("SHIP-")
    assert len(data["shipment_id"]) == len("SHIP-") + 8
    assert data["id"] is not None
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


def test_post_shipment_response_validates_against_schema(client_fixture, seeded_db):
    """Regression test: POST /shipments response must conform to ShipmentResponse schema."""
    payload = {
        "product_id": "0x" + "b" * 64,
        "origin": "Schema Validation Origin",
        "destination": "Schema Validation Destination",
        "status": "0",
    }
    response = client_fixture.post("/shipments", json=payload)
    assert response.status_code == 200
    data = response.json()
    validated = ShipmentResponse.model_validate(data)
    assert validated.origin == payload["origin"]
    assert validated.created_at is not None
    assert validated.updated_at is not None


def test_post_shipment_returns_422_for_nonexistent_product(client_fixture, seeded_db):
    """Creating a shipment for a non-existent product should fail gracefully."""
    payload = {
        "product_id": "0xnonexistent",
        "origin": "Origin",
        "destination": "Destination",
        "status": "0",
    }
    response = client_fixture.post("/shipments", json=payload)
    assert response.status_code == 422
    assert "Product not found" in response.json()["detail"]


def test_put_shipment_updates_existing_shipment(client_fixture, seeded_db):
    create_payload = {
        "product_id": "0x" + "b" * 64,
        "origin": "Old Origin",
        "destination": "Old Destination",
        "status": "0",
        "notes": "Old notes",
    }
    create_response = client_fixture.post("/shipments", json=create_payload)
    shipment_id = create_response.json()["shipment_id"]

    update_payload = {
        "origin": "New Origin",
        "notes": "Updated notes",
    }
    response = client_fixture.put(f"/shipments/{shipment_id}", json=update_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["origin"] == "New Origin"
    assert data["status"] == "0"
    assert data["notes"] == "Updated notes"
    assert data["destination"] == "Old Destination"
    assert data["shipment_id"] == shipment_id


def test_put_shipment_response_validates_against_schema(client_fixture, seeded_db):
    """Regression test: PUT /shipments/{id} response must conform to ShipmentResponse schema."""
    create_payload = {
        "product_id": "0x" + "b" * 64,
        "origin": "Old Origin",
        "destination": "Old Destination",
        "status": "0",
        "notes": "Old notes",
    }
    create_response = client_fixture.post("/shipments", json=create_payload)
    shipment_id = create_response.json()["shipment_id"]

    update_payload = {
        "origin": "New Origin",
        "notes": "Updated notes",
    }
    response = client_fixture.put(f"/shipments/{shipment_id}", json=update_payload)
    assert response.status_code == 200
    data = response.json()
    validated = ShipmentResponse.model_validate(data)
    assert validated.origin == update_payload["origin"]
    assert validated.status == "0"
    assert validated.created_at is not None
    assert validated.updated_at is not None


def test_put_shipment_returns_404_for_nonexistent_shipment(client_fixture, seeded_db):
    response = client_fixture.put("/shipments/SHIP-NONEXISTENT", json={"origin": "New"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Shipment not found"


def test_get_shipments_returns_paginated_list_with_items_and_total(client_fixture, seeded_db):
    for i in range(2):
        client_fixture.post("/shipments", json={
            "product_id": "0x" + ("b" if i == 0 else "c") * 64,
            "origin": f"Origin {i}",
            "destination": f"Destination {i}",
            "status": "0",
        })

    response = client_fixture.get("/shipments")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_get_shipments_filters_by_status_correctly(client_fixture, seeded_db):
    client_fixture.post("/shipments", json={
        "product_id": "0x" + "b" * 64,
        "origin": "Warehouse A",
        "destination": "Store B",
        "status": "0",
    })
    client_fixture.post("/shipments", json={
        "product_id": "0x" + "c" * 64,
        "origin": "Warehouse C",
        "destination": "Store D",
        "status": "0",
    })
    # Status is projected by the indexer, never supplied as a planning write.
    seeded_db.query(Shipment).filter(Shipment.origin == "Warehouse C").update({"status": "1"})
    seeded_db.commit()

    response = client_fixture.get("/shipments?status=1")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["status"] == "1"
    assert data["items"][0]["origin"] == "Warehouse C"


def test_get_history(client_fixture, seeded_db):
    response = client_fixture.get("/shipments/0x" + "b" * 64 + "/history")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["location"] == "Origin"
    assert data[1]["location"] == "Midpoint"


def test_get_history_empty(client_fixture, seeded_db):
    response = client_fixture.get("/shipments/0xnonexistent/history")
    assert response.status_code == 200
    data = response.json()
    assert data == []


def test_get_transfers(client_fixture, seeded_db):
    response = client_fixture.get("/shipments/0x" + "b" * 64 + "/transfers")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["from_address"] == "0xhandler1"


def test_get_transfers_empty(client_fixture, seeded_db):
    response = client_fixture.get("/shipments/0xnonexistent/transfers")
    assert response.status_code == 200
    data = response.json()
    assert data == []


def test_get_shipments_response_validates_against_schema(client_fixture, seeded_db):
    """GET /shipments response must conform to ShipmentListResponse schema."""
    for i in range(2):
        client_fixture.post("/shipments", json={
            "product_id": "0x" + ("b" if i == 0 else "c") * 64,
            "origin": f"Origin {i}",
            "destination": f"Destination {i}",
            "status": "0",
        })
    response = client_fixture.get("/shipments")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"items", "total"}
    validated = ShipmentListResponse.model_validate(data)
    assert validated.total == 2
    assert len(validated.items) == 2
    for item in validated.items:
        assert isinstance(item, ShipmentResponse)


def test_get_shipments_empty_list_contract(client_fixture, seeded_db):
    """GET /shipments with no shipments must return a valid empty list."""
    response = client_fixture.get("/shipments")
    assert response.status_code == 200
    data = response.json()
    validated = ShipmentListResponse.model_validate(data)
    assert validated.total == 0
    assert validated.items == []


def test_get_history_validates_against_schema(client_fixture, seeded_db):
    """GET /shipments/{id}/history items must conform to CheckpointResponse schema."""
    response = client_fixture.get("/shipments/0x" + "b" * 64 + "/history")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    for cp in data:
        validated = CheckpointResponse.model_validate(cp)
        assert validated.product_id == "0x" + "b" * 64


def test_get_transfers_validates_against_schema(client_fixture, seeded_db):
    """GET /shipments/{id}/transfers items must conform to CustodyTransferResponse schema."""
    response = client_fixture.get("/shipments/0x" + "b" * 64 + "/transfers")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    for ct in data:
        validated = CustodyTransferResponse.model_validate(ct)
        assert validated.product_id == "0x" + "b" * 64


def test_get_shipments_filters_by_search_origin(client_fixture, seeded_db):
    """GET /shipments?search=<origin_term> must return only matching shipments."""
    client_fixture.post("/shipments", json={
        "product_id": "0x" + "b" * 64,
        "origin": "Alpha Warehouse",
        "destination": "Beta Store",
        "status": "0",
    })
    client_fixture.post("/shipments", json={
        "product_id": "0x" + "c" * 64,
        "origin": "Gamma Port",
        "destination": "Delta Hub",
        "status": "0",
    })
    response = client_fixture.get("/shipments?search=Alpha")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["origin"] == "Alpha Warehouse"


def test_get_shipments_filters_by_search_destination(client_fixture, seeded_db):
    """GET /shipments?search=<destination_term> must return only matching shipments."""
    client_fixture.post("/shipments", json={
        "product_id": "0x" + "b" * 64,
        "origin": "Alpha Warehouse",
        "destination": "Beta Store",
        "status": "0",
    })
    client_fixture.post("/shipments", json={
        "product_id": "0x" + "c" * 64,
        "origin": "Gamma Port",
        "destination": "Delta Hub",
        "status": "0",
    })
    response = client_fixture.get("/shipments?search=Delta")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["destination"] == "Delta Hub"


def test_get_shipments_search_returns_empty_when_no_match(client_fixture, seeded_db):
    """GET /shipments?search=<nonexistent> must return empty list with total=0."""
    client_fixture.post("/shipments", json={
        "product_id": "0x" + "b" * 64,
        "origin": "Origin X",
        "destination": "Destination Y",
        "status": "0",
    })
    response = client_fixture.get("/shipments?search=ZZZNoMatch")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []
