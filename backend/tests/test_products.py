import pytest

from app.models.product import Product
from app.schemas.product import ProductListResponse, ProductResponse
from app.schemas.shipment import CheckpointResponse, CustodyTransferResponse
from datetime import datetime, timezone


@pytest.fixture(scope="function")
def seeded_products(db_session):
    product = Product(
        product_id="0x" + "a" * 64,
        name="Test Product",
        description="A test product",
        metadata_uri="ipfs://test",
        manufacturer_address="0x1234567890123456789012345678901234567890",
        registered_at=datetime.now(timezone.utc),
        block_number=100,
        tx_hash="0xtesttx",
    )
    db_session.add(product)
    db_session.commit()
    return db_session


def test_post_product_creates_product_successfully(client_fixture, seeded_products):
    """Regression test: POST /products must not return 405 Method Not Allowed."""
    payload = {
        "name": "Organic Coffee Beans",
        "manufacturer_address": "0x0987654321098765432109876543210987654321",
        "description": "Premium organic coffee",
        "metadata_uri": "https://example.com/coffee",
    }
    response = client_fixture.post("/products", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == payload["name"]
    assert data["manufacturer_address"] == payload["manufacturer_address"]
    assert data["description"] == payload["description"]
    assert data["metadata_uri"] == payload["metadata_uri"]
    assert data["block_number"] == 0
    assert data["tx_hash"] == "0x"


def test_post_product_returns_created_product_with_generated_id(client_fixture, seeded_products):
    payload = {
        "name": "New Product",
        "manufacturer_address": "0x1234567890123456789012345678901234567890",
    }
    response = client_fixture.post("/products", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "product_id" in data
    assert data["product_id"].startswith("PROD-")
    assert len(data["product_id"]) == len("PROD-") + 8
    assert data["id"] is not None
    assert data["registered_at"] is not None


def test_post_product_response_validates_against_schema(client_fixture, seeded_products):
    """Regression test: POST /products response must conform to ProductResponse schema."""
    payload = {
        "name": "Schema Validation Product",
        "manufacturer_address": "0x1234567890123456789012345678901234567890",
    }
    response = client_fixture.post("/products", json=payload)
    assert response.status_code == 200
    data = response.json()
    validated = ProductResponse.model_validate(data)
    assert validated.name == payload["name"]
    assert validated.registered_at is not None
    assert "created_at" not in data


def test_put_product_updates_existing_product(client_fixture, seeded_products):
    update_payload = {
        "name": "Updated Product Name",
        "description": "Updated description",
    }
    response = client_fixture.put("/products/0x" + "a" * 64, json=update_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Product Name"
    assert data["description"] == "Updated description"
    assert data["manufacturer_address"] == "0x1234567890123456789012345678901234567890"


def test_put_product_response_validates_against_schema(client_fixture, seeded_products):
    """Regression test: PUT /products/{id} response must conform to ProductResponse schema."""
    update_payload = {
        "name": "Updated Product Name",
        "description": "Updated description",
    }
    response = client_fixture.put("/products/0x" + "a" * 64, json=update_payload)
    assert response.status_code == 200
    data = response.json()
    validated = ProductResponse.model_validate(data)
    assert validated.name == update_payload["name"]
    assert validated.description == update_payload["description"]
    assert validated.registered_at is not None
    assert "created_at" not in data


def test_put_product_returns_404_for_nonexistent_product(client_fixture, seeded_products):
    response = client_fixture.put("/products/0xnonexistent", json={"name": "New"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Product not found"


def test_get_products_returns_paginated_list_with_items_and_total(client_fixture, seeded_products):
    response = client_fixture.get("/products")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    assert data["total"] >= 1
    assert len(data["items"]) >= 1


def test_get_product_detail(client_fixture, seeded_products):
    response = client_fixture.get("/products/0x" + "a" * 64)
    assert response.status_code == 200
    data = response.json()
    assert "product" in data
    assert data["product"]["name"] == "Test Product"
    assert "history" in data
    assert "transfers" in data


def test_get_product_verify(client_fixture, seeded_products):
    response = client_fixture.get("/products/0x" + "a" * 64 + "/verify")
    assert response.status_code == 200
    data = response.json()
    assert data["product_id"] == "0x" + "a" * 64
    assert data["is_registered"] is False
    assert data["checkpoint_count"] == 0
    assert data["is_delivered"] is False


def test_get_product_detail_404(client_fixture, seeded_products):
    response = client_fixture.get("/products/0xnonexistent")
    assert response.status_code == 404
    assert response.json()["detail"] == "Product not found"


def test_get_product_verify_404(client_fixture, seeded_products):
    response = client_fixture.get("/products/0xnonexistent/verify")
    assert response.status_code == 404
    assert response.json()["detail"] == "Product not found"


def test_get_products_response_validates_against_schema(client_fixture, seeded_products):
    """GET /products response must conform to ProductListResponse schema."""
    response = client_fixture.get("/products")
    assert response.status_code == 200
    data = response.json()
    validated = ProductListResponse.model_validate(data)
    assert validated.total >= 1
    assert isinstance(validated.items, list)
    assert len(validated.items) >= 1
    for item in validated.items:
        assert isinstance(item, ProductResponse)


def test_get_product_detail_contract(client_fixture, seeded_products):
    """GET /products/{id} response must contain validated product, history, and transfers."""
    response = client_fixture.get("/products/0x" + "a" * 64)
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"product", "history", "transfers"}
    product = ProductResponse.model_validate(data["product"])
    assert product.product_id == "0x" + "a" * 64
    assert isinstance(data["history"], list)
    assert isinstance(data["transfers"], list)
    for cp in data["history"]:
        CheckpointResponse.model_validate(cp)
    for ct in data["transfers"]:
        CustodyTransferResponse.model_validate(ct)


def test_get_product_verify_contract(client_fixture, seeded_products):
    """GET /products/{id}/verify response must match expected contract shape."""
    response = client_fixture.get("/products/0x" + "a" * 64 + "/verify")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"product_id", "is_registered", "is_delivered", "checkpoint_count"}
    assert data["product_id"] == "0x" + "a" * 64
    assert isinstance(data["is_registered"], bool)
    assert isinstance(data["is_delivered"], bool)
    assert isinstance(data["checkpoint_count"], int)


def test_get_products_filters_by_search_term(client_fixture, seeded_products):
    """GET /products?search=<term> must only return products whose name contains the term."""
    # Create a second product with a different name
    client_fixture.post("/products", json={
        "name": "Completely Different Widget",
        "manufacturer_address": "0x1234567890123456789012345678901234567890",
    })
    response = client_fixture.get("/products?search=Test")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Test Product"


def test_get_products_search_returns_empty_when_no_match(client_fixture, seeded_products):
    """GET /products?search=<nonexistent> must return empty list with total=0."""
    response = client_fixture.get("/products?search=ZZZNoMatch")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_get_products_search_is_case_insensitive(client_fixture, seeded_products):
    """GET /products?search= must match regardless of case."""
    response = client_fixture.get("/products?search=test%20product")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Test Product"
