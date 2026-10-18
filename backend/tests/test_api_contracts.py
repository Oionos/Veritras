import pytest
from datetime import datetime, timezone

from app.services.identity import scope_values
from app.models.product import Product
from app.models.shipment import Checkpoint, CustodyTransfer, Shipment
from app.schemas.product import ProductListResponse, ProductResponse
from app.schemas.shipment import (
    CheckpointResponse,
    CustodyTransferResponse,
    ShipmentListResponse,
    ShipmentResponse,
)
from app.schemas.analytics import KPIResponse, AnomalyResponse


@pytest.fixture(scope="function")
def seeded_product(db_session):
    product = Product(
        product_id="0x" + "c" * 64,
        name="Contract Test Product",
        description="For contract tests",
        metadata_uri="ipfs://contract",
        manufacturer_address="0x1234567890123456789012345678901234567890",
        owner_address="0x1234567890123456789012345678901234567890",
        ownership_source="signed_draft",
        **scope_values("0x" + "c" * 64),
        registration_status="draft",
        created_at=datetime.now(timezone.utc),
        registered_at=datetime.now(timezone.utc),
        block_number=0,
        tx_hash="0x",
    )
    db_session.add(product)
    db_session.commit()
    return product


@pytest.fixture(scope="function")
def seeded_shipment(db_session, seeded_product):
    shipment = Shipment(
        shipment_id="SHIP-CONTRACT01",
        product_id=seeded_product.product_id,
        origin="Origin",
        destination="Dest",
        status="0",
        notes="Notes",
    )
    db_session.add(shipment)

    cp1 = Checkpoint(
        product_id=seeded_product.product_id,
        location="Loc1",
        status="0",
        handler_address="0xh1",
        notes=None,
        timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        block_number=101,
        tx_hash="0xcp1",
    )
    cp2 = Checkpoint(
        product_id=seeded_product.product_id,
        location="Loc2",
        status="1",
        handler_address="0xh2",
        notes=None,
        timestamp=datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc),
        block_number=102,
        tx_hash="0xcp2",
    )
    db_session.add_all([cp1, cp2])

    transfer = CustodyTransfer(
        product_id=seeded_product.product_id,
        from_address="0xh1",
        to_address="0xh2",
        timestamp=datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc),
        block_number=103,
        tx_hash="0xtr1",
    )
    db_session.add(transfer)
    db_session.commit()
    return shipment


class TestProductEndpointContracts:
    def test_list_products_contract(self, client_fixture, seeded_product):
        response = client_fixture.get("/products")
        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) == {"items", "total"}
        validated = ProductListResponse.model_validate(data)
        assert validated.total >= 1
        assert isinstance(validated.items, list)
        for item in validated.items:
            assert isinstance(item, ProductResponse)

    def test_list_products_empty_contract(self, client_fixture, db_session):
        response = client_fixture.get("/products")
        assert response.status_code == 200
        data = response.json()
        validated = ProductListResponse.model_validate(data)
        assert validated.total == 0
        assert validated.items == []

    def test_create_product_contract(self, client_fixture, seeded_product):
        payload = {
            "name": "New Contract Product",
            "manufacturer_address": "0x1234567890123456789012345678901234567890",
        }
        response = client_fixture.post("/products", json=payload)
        assert response.status_code == 200
        data = response.json()
        validated = ProductResponse.model_validate(data)
        assert validated.name == payload["name"]
        assert validated.block_number == 0
        assert validated.tx_hash == "0x"

    def test_update_product_contract(self, client_fixture, seeded_product):
        payload = {"name": "Updated Contract Name"}
        response = client_fixture.put(
            f"/products/{seeded_product.product_id}", json=payload
        )
        assert response.status_code == 200
        data = response.json()
        validated = ProductResponse.model_validate(data)
        assert validated.name == "Updated Contract Name"

    def test_get_product_detail_contract(self, client_fixture, seeded_product):
        response = client_fixture.get(f"/products/{seeded_product.product_id}")
        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) == {"product", "history", "transfers"}
        product = ProductResponse.model_validate(data["product"])
        assert product.product_id == seeded_product.product_id
        for cp in data["history"]:
            CheckpointResponse.model_validate(cp)
        for ct in data["transfers"]:
            CustodyTransferResponse.model_validate(ct)

    def test_get_product_verify_contract(self, client_fixture, seeded_product):
        response = client_fixture.get(f"/products/{seeded_product.product_id}/verify")
        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) == {
            "product_id",
            "is_registered",
            "is_delivered",
            "checkpoint_count",
            "synchronization",
            "evidence",
        }
        assert data["product_id"] == seeded_product.product_id
        assert data["is_registered"] is False  # A seeded row is not receipt evidence.
        assert isinstance(data["is_delivered"], bool)
        assert isinstance(data["checkpoint_count"], int)

    def test_get_product_404_contract(self, client_fixture, seeded_product):
        response = client_fixture.get("/products/0xnonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert data["detail"] == "Product not found"


class TestShipmentEndpointContracts:
    def test_list_shipments_contract(self, client_fixture, seeded_shipment):
        response = client_fixture.get("/shipments")
        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) == {"items", "total"}
        validated = ShipmentListResponse.model_validate(data)
        assert validated.total >= 1
        assert isinstance(validated.items, list)
        for item in validated.items:
            assert isinstance(item, ShipmentResponse)

    def test_list_shipments_empty_contract(self, client_fixture, db_session):
        response = client_fixture.get("/shipments")
        assert response.status_code == 200
        data = response.json()
        validated = ShipmentListResponse.model_validate(data)
        assert validated.total == 0
        assert validated.items == []

    def test_create_shipment_contract(self, client_fixture, seeded_product):
        payload = {
            "product_id": seeded_product.product_id,
            "origin": "O",
            "destination": "D",
            "status": "0",
        }
        response = client_fixture.post("/shipments", json=payload)
        assert response.status_code == 200
        data = response.json()
        validated = ShipmentResponse.model_validate(data)
        assert validated.origin == "O"

    def test_update_shipment_contract(self, client_fixture, seeded_shipment):
        payload = {"origin": "Updated Origin"}
        response = client_fixture.put(
            f"/shipments/{seeded_shipment.shipment_id}", json=payload
        )
        assert response.status_code == 200
        data = response.json()
        validated = ShipmentResponse.model_validate(data)
        assert validated.origin == "Updated Origin"

    def test_get_history_contract(self, client_fixture, seeded_shipment):
        response = client_fixture.get(
            f"/shipments/{seeded_shipment.product_id}/history"
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        for cp in data:
            CheckpointResponse.model_validate(cp)

    def test_get_history_empty_contract(self, client_fixture, seeded_product):
        response = client_fixture.get(f"/shipments/{seeded_product.product_id}/history")
        assert response.status_code == 200
        data = response.json()
        assert data == []

    def test_get_transfers_contract(self, client_fixture, seeded_shipment):
        response = client_fixture.get(
            f"/shipments/{seeded_shipment.product_id}/transfers"
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        for ct in data:
            CustodyTransferResponse.model_validate(ct)

    def test_get_transfers_empty_contract(self, client_fixture, seeded_product):
        response = client_fixture.get(
            f"/shipments/{seeded_product.product_id}/transfers"
        )
        assert response.status_code == 200
        data = response.json()
        assert data == []

    def test_get_shipment_404_contract(self, client_fixture, seeded_shipment):
        response = client_fixture.put(
            "/shipments/SHIP-NONEXISTENT", json={"origin": "New"}
        )
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert data["detail"] == "Shipment not found"


class TestAnalyticsEndpointContracts:
    def test_get_kpis_contract(self, client_fixture, seeded_shipment):
        response = client_fixture.get("/analytics/kpis")
        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) == set(KPIResponse.model_fields)
        validated = KPIResponse.model_validate(data)
        assert isinstance(validated.bottleneck_locations, list)
        assert validated.total_shipments >= 0

    def test_get_anomalies_contract(self, client_fixture, seeded_shipment):
        response = client_fixture.get("/analytics/anomalies")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        for item in data:
            AnomalyResponse.model_validate(item)
            assert set(item.keys()) == {
                "product_id",
                "transit_time_hours",
                "z_score",
                "severity",
                "flagged_at",
            }

    def test_get_anomalies_empty_contract(self, client_fixture, db_session):
        response = client_fixture.get("/analytics/anomalies")
        assert response.status_code == 200
        data = response.json()
        assert data == []

    def test_get_bottlenecks_contract(self, client_fixture, seeded_shipment):
        response = client_fixture.get("/analytics/bottlenecks")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            assert set(data[0].keys()) == {
                "location",
                "avg_dwell_hours",
                "incident_count",
            }

    def test_export_csv_contract(self, client_fixture, seeded_shipment):
        response = client_fixture.get("/analytics/export?format=csv")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"

    def test_export_pdf_contract(self, client_fixture, seeded_shipment):
        response = client_fixture.get("/analytics/export?format=pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"


class TestOpenAPISchema:
    def test_openapi_json_returns_valid_schema(self, client_fixture):
        response = client_fixture.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "openapi" in schema
        assert schema["openapi"].startswith("3.")
        assert "paths" in schema
        assert "components" in schema
        assert "schemas" in schema["components"]

    def test_expected_paths_exist(self, client_fixture):
        response = client_fixture.get("/openapi.json")
        schema = response.json()
        paths = schema["paths"]
        expected_paths = [
            "/products/",
            "/products/{product_id}",
            "/products/{product_id}/verify",
            "/shipments/",
            "/shipments/{shipment_id}",
            "/shipments/{product_id}/history",
            "/shipments/{product_id}/transfers",
            "/analytics/kpis",
            "/analytics/anomalies",
            "/analytics/bottlenecks",
            "/analytics/export",
            "/health",
        ]
        for path in expected_paths:
            assert path in paths, f"Expected path {path} not found in OpenAPI schema"

    def test_expected_schemas_defined(self, client_fixture):
        response = client_fixture.get("/openapi.json")
        schema = response.json()
        schemas = schema["components"]["schemas"]
        expected_schemas = [
            "ProductResponse",
            "ProductListResponse",
            "ProductCreate",
            "ProductUpdate",
            "ShipmentResponse",
            "ShipmentListResponse",
            "ShipmentCreate",
            "ShipmentUpdate",
            "CheckpointResponse",
            "CustodyTransferResponse",
            "KPIResponse",
            "AnomalyResponse",
            "HTTPValidationError",
            "ValidationError",
        ]
        for name in expected_schemas:
            assert (
                name in schemas
            ), f"Expected schema {name} not found in OpenAPI schema"
