from datetime import datetime, timezone
import pytest
from app.models.chain import ChainEvent, IndexedProduct
from app.models.product import ProductAlias


@pytest.fixture
def journey(client_fixture, db_session):
    product = client_fixture.post(
        "/products",
        json={
            "name": "Coffee",
            "manufacturer_address": "0x1234567890123456789012345678901234567890",
        },
    ).json()
    shipment = client_fixture.post(
        "/shipments",
        json={
            "product_id": product["product_id"],
            "origin": "Manila",
            "destination": "Cebu",
        },
    ).json()
    db_session.add(
        IndexedProduct(
            scope="journey",
            product_key=product["on_chain_product_id"],
            product_id=product["product_id"],
            baseline={},
            current_handler="0x" + "5" * 40,
            status="1",
        )
    )
    db_session.commit()
    client_fixture.headers.pop("Authorization")
    return product, shipment


def event(product, number, **changes):
    fields = dict(
        occurrence_id=str(number),
        event_id=str(number),
        scope="journey",
        chain_id=product["chain_id"],
        product_key=product["on_chain_product_id"],
        contract_address=product["tracker_address"],
        transaction_hash="0x" + f"{number:064x}",
        block_hash="0x" + "a" * 64,
        block_number=10,
        transaction_index=number,
        log_index=0,
        event_type="CheckpointRecorded",
        canonical=True,
        processed_at=datetime.now(timezone.utc),
        payload={
            "timestamp": 1700000000,
            "location": "Manila",
            "status": 1,
            "handler": "0x" + "5" * 40,
            "notes": "<script>text only</script>",
        },
    )
    fields.update(changes)
    return ChainEvent(**fields)


def test_public_shipment_lookup_and_missing(journey, client_fixture):
    product, shipment = journey
    response = client_fixture.get("/shipments/" + shipment["shipment_id"])
    assert response.status_code == 200
    assert response.json()["product_id"] == product["product_id"]
    assert response.json()["current_handler"] == "0x" + "5" * 40
    assert client_fixture.get("/shipments/does-not-exist").status_code == 404


def test_timeline_order_scope_alias_and_orphan_exclusion(
    journey, client_fixture, db_session
):
    product, _ = journey
    # Same-block ordering must follow transaction/log positions, not timestamps.
    db_session.add_all(
        [
            event(
                product,
                3,
                transaction_index=1,
                log_index=1,
                event_type="DeliveryCompleted",
            ),
            event(
                product,
                2,
                transaction_index=1,
                log_index=0,
                event_type="CustodyTransferred",
                payload={"from": "manufacturer", "to": "carrier"},
            ),
            event(product, 1, transaction_index=0),
            event(product, 4, canonical=False),
            event(product, 5, scope="another-environment"),
            event(product, 6, product_key="0x" + "f" * 64),
            event(product, 7, chain_id=1),
            event(product, 8, contract_address="0x" + "9" * 40),
        ]
    )
    db_session.add(
        ProductAlias(alias_id="OLD-PRODUCT", product_id=product["product_id"])
    )
    db_session.commit()
    response = client_fixture.get("/products/OLD-PRODUCT/timeline").json()
    assert response["product_id"] == product["product_id"]
    assert response["chain_id"] == product["chain_id"]
    assert response["total"] == 3
    assert [item["event_id"] for item in response["items"]] == ["1", "2", "3"]
    assert response["items"][0]["notes"] == "<script>text only</script>"
    assert response["items"][1]["from_address"] == "manufacturer"
    assert response["items"][1]["to_address"] == "carrier"
    assert response["items"][1]["timestamp"] is None


def test_timeline_paginates_without_losing_events(journey, client_fixture, db_session):
    product, _ = journey
    db_session.add_all([event(product, i) for i in range(105)])
    db_session.commit()
    path = f"/products/{product['product_id']}/timeline"
    first = client_fixture.get(path).json()
    second = client_fixture.get(path + "?skip=100").json()
    assert first["total"] == second["total"] == 105
    assert len(first["items"]) == 100
    assert [item["event_id"] for item in second["items"]] == [
        str(i) for i in range(100, 105)
    ]
    assert client_fixture.get(path + "?skip=-1").status_code == 422
    assert client_fixture.get(path + "?limit=101").status_code == 422
    assert client_fixture.get("/products/missing/timeline").status_code == 404


def test_legacy_without_binding_has_no_manufactured_evidence(
    journey, client_fixture, db_session
):
    product, _ = journey
    db_session.add(event(product, 1))
    db_session.query(IndexedProduct).delete()
    db_session.commit()
    response = client_fixture.get(f"/products/{product['product_id']}/timeline").json()
    assert response["items"] == []
    assert response["total"] == 0
