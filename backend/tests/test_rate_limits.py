"""Integration tests for per-route rate limits on write endpoints.

slowapi uses an in-memory store. We reset the limiter storage before each
test to avoid state bleeding between tests.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.limiter import limiter


@pytest.fixture(autouse=True)
def reset_limiter():
    """Clear all rate-limit counters before and after every test."""
    limiter._storage.reset()
    yield
    limiter._storage.reset()


def test_post_products_allows_up_to_limit(client_fixture):
    """30 POST /products requests must all succeed (not 429)."""
    payload = {
        "name": "Test Product",
        "manufacturer_address": "0x1234567890123456789012345678901234567890",
    }
    for i in range(30):
        r = client_fixture.post("/products/", json=payload)
        assert r.status_code != 429, f"Request {i+1} was unexpectedly rate-limited"


def test_post_products_returns_429_when_limit_exceeded(client_fixture):
    """The 31st POST /products within a minute must return 429."""
    payload = {
        "name": "Test Product",
        "manufacturer_address": "0x1234567890123456789012345678901234567890",
    }
    for _ in range(30):
        client_fixture.post("/products/", json=payload)
    r = client_fixture.post("/products/", json=payload)
    assert r.status_code == 429


def test_post_shipments_returns_429_when_limit_exceeded(client_fixture):
    """The 31st POST /shipments within a minute must return 429."""
    from app.models.product import Product
    from datetime import datetime, timezone
    from tests.conftest import TestingSessionLocal

    # Seed one product so the first requests pass FK validation
    db = TestingSessionLocal()
    product = Product(
        product_id="PROD-TEST01",
        name="Seed Product",
        manufacturer_address="0x1234567890123456789012345678901234567890",
        registered_at=datetime.now(timezone.utc),
        block_number=0,
        tx_hash="0x",
    )
    db.add(product)
    db.commit()
    db.close()

    payload = {
        "product_id": "PROD-TEST01",
        "origin": "London",
        "destination": "Paris",
        "status": "0",
    }
    for _ in range(30):
        client_fixture.post("/shipments/", json=payload)
    r = client_fixture.post("/shipments/", json=payload)
    assert r.status_code == 429


def test_put_shipments_returns_429_when_limit_exceeded(client_fixture):
    """The 31st PUT /shipments/{id} within a minute must return 429.

    The shipment doesn't need to exist — slowapi counts and limits the request
    before the route handler resolves the DB lookup.
    """
    payload = {"notes": "update"}
    for _ in range(30):
        client_fixture.put("/shipments/SHIP-FAKE99", json=payload)
    r = client_fixture.put("/shipments/SHIP-FAKE99", json=payload)
    assert r.status_code == 429
