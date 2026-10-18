from types import SimpleNamespace
from unittest.mock import MagicMock
from datetime import datetime, timezone
import pytest
from web3.exceptions import TransactionNotFound
from app.core.auth import create_access_token
from app.models.product import Product
from app.models.registration import RegistrationAttempt
from app.models.chain import ChainEvent, IndexedProduct
from app.services import registration

OWNER = "0x1234567890123456789012345678901234567890"
HASH = "0x" + "a" * 64
OTHER = "0x" + "c" * 64


@pytest.fixture
def draft(client_fixture):
    response = client_fixture.post(
        "/products",
        json={
            "name": "Widget",
            "description": "Description",
            "metadata_uri": "ipfs://one",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_submission_persists_idempotently_without_granting_registration(
    client_fixture, draft, db_session
):
    path = f"/products/{draft['product_id']}/registration"
    response = client_fixture.post(path, json={"tx_hash": HASH})
    assert response.status_code == 200
    assert response.json()["status"] == "submitted"
    assert client_fixture.post(path, json={"tx_hash": HASH}).json() == response.json()
    assert db_session.query(RegistrationAttempt).count() == 1
    db_session.expire_all()
    assert db_session.query(Product).first().registration_status == "draft"
    assert client_fixture.get(path).json()["attempts"][0]["tx_hash"] == HASH
    evidence = client_fixture.get(f"/products/{draft['product_id']}/verify").json()
    assert evidence["is_registered"] is False
    assert evidence["evidence"]["status"] == "unavailable"


def test_submission_and_reconciliation_require_owner(client_fixture, draft):
    path = f"/products/{draft['product_id']}/registration"
    client_fixture.headers["Authorization"] = "Bearer " + create_access_token(
        "0x" + "3" * 40
    )
    assert client_fixture.post(path, json={"tx_hash": HASH}).status_code == 403
    assert (
        client_fixture.post(path + "/reconcile", params={"tx_hash": HASH}).status_code
        == 403
    )
    client_fixture.headers.pop("Authorization")
    assert client_fixture.post(path, json={"tx_hash": HASH}).status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"tx_hash": "invented"},
        {"tx_hash": HASH, "status": "indexed"},
        {"tx_hash": HASH, "operation": "other"},
    ],
)
def test_invalid_submissions_rejected(client_fixture, draft, payload):
    assert (
        client_fixture.post(
            f"/products/{draft['product_id']}/registration", json=payload
        ).status_code
        == 422
    )


def test_pending_attempt_locks_edits_and_failed_attempt_allows_retry(
    client_fixture, draft, monkeypatch
):
    path = f"/products/{draft['product_id']}"
    client_fixture.post(path + "/registration", json={"tx_hash": HASH})
    assert client_fixture.put(path, json={"name": "Changed"}).status_code == 409
    monkeypatch.setattr(
        registration,
        "observe",
        lambda *args: dict(
            status="failed",
            reason="transaction_reverted",
            nonce=1,
            block_number=10,
            block_hash="0x" + "b" * 64,
        ),
    )
    result = client_fixture.post(
        path + "/registration/reconcile", params={"tx_hash": HASH}
    )
    assert result.json()["status"] == "failed"
    assert (
        client_fixture.post(path + "/registration", json={"tx_hash": OTHER}).status_code
        == 200
    )
    assert len(client_fixture.get(path + "/registration").json()["attempts"]) == 2


@pytest.fixture
def chain(draft, db_session, monkeypatch):
    product = db_session.query(Product).first()
    attempt = RegistrationAttempt(
        product_id=product.product_id,
        chain_id=product.chain_id,
        registry_address=product.registry_address,
        submitted_by=OWNER,
        tx_hash=HASH,
        operation="registration",
        status="submitted",
        reason="awaiting_receipt",
        created_at=datetime.now(timezone.utc),
        registration_payload={
            "name": "Widget",
            "description": "Description",
            "metadataURI": "ipfs://one",
        },
    )
    db_session.add(attempt)
    db_session.commit()
    registry = MagicMock()
    registry.decode_function_input.return_value = (
        SimpleNamespace(fn_name="registerProduct"),
        dict(
            productId=bytes.fromhex(product.on_chain_product_id[2:]),
            name="Widget",
            description="Description",
            metadataURI="ipfs://one",
        ),
    )
    event = {
        "address": product.registry_address,
        "args": {
            "productId": bytes.fromhex(product.on_chain_product_id[2:]),
            "manufacturer": OWNER,
            "name": "Widget",
        },
    }
    registry.events.ProductRegistered.return_value.process_receipt.return_value = [
        event
    ]
    w3 = MagicMock()
    w3.eth.contract.return_value = registry
    tx = {"from": OWNER, "to": product.registry_address, "nonce": 7, "input": "0x1234"}
    receipt = {
        "status": 1,
        "to": product.registry_address,
        "blockNumber": 10,
        "blockHash": bytes.fromhex("bb" * 32),
    }
    w3.eth.get_transaction.return_value = tx
    w3.eth.get_transaction_receipt.return_value = receipt
    w3.eth.get_block.return_value = {"hash": receipt["blockHash"]}
    w3.eth.block_number = 22
    monkeypatch.setattr(registration, "rpc", lambda: w3)
    return product, attempt, w3, tx, receipt, event, registry


def test_confirming_indexing_and_indexed_require_matching_journal(chain, db_session):
    product, attempt, w3, *_ = chain
    w3.eth.block_number = 21
    registration.reconcile(db_session, product, attempt)
    assert attempt.status == "confirming"
    w3.eth.block_number = 22
    registration.reconcile(db_session, product, attempt)
    assert attempt.status == "indexing"
    assert registration.evidence(db_session, product)["status"] == "pending"
    db_session.add(
        IndexedProduct(
            scope="test",
            product_key=product.on_chain_product_id,
            product_id=product.product_id,
            baseline={},
        )
    )
    db_session.add(
        ChainEvent(
            occurrence_id="test",
            scope="test",
            event_id="test",
            chain_id=product.chain_id,
            contract_address=product.registry_address,
            transaction_hash=HASH,
            log_index=0,
            transaction_index=0,
            block_number=10,
            block_hash="0x" + "bb" * 32,
            event_type="ProductRegistered",
            product_key=product.on_chain_product_id,
            payload={},
            canonical=True,
            processed_at=datetime.now(timezone.utc),
        )
    )
    product.registration_status = "indexed"
    product.block_number = 10
    product.tx_hash = HASH
    db_session.commit()
    db_session.expire_all()
    registration.reconcile(db_session, product, attempt)
    assert attempt.status == "indexed"
    assert registration.evidence(db_session, product)["status"] == "verified"
    db_session.query(ChainEvent).first().canonical = False
    db_session.flush()
    assert registration.evidence(db_session, product)["status"] == "pending"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("sender", "transaction_identity_mismatch"),
        ("contract", "transaction_identity_mismatch"),
        ("input", "transaction_input_mismatch"),
        ("event", "registration_event_mismatch"),
        ("reverted", "transaction_reverted"),
        ("orphan", "receipt_reorganized"),
    ],
)
def test_bad_evidence_never_verifies(chain, db_session, mutation, reason):
    product, attempt, w3, tx, receipt, event, registry = chain
    if mutation == "sender":
        tx["from"] = "0x" + "4" * 40
    if mutation == "contract":
        tx["to"] = "0x" + "4" * 40
    if mutation == "input":
        registry.decode_function_input.side_effect = ValueError("bad")
    if mutation == "event":
        event["args"]["manufacturer"] = "0x" + "4" * 40
    if mutation == "reverted":
        receipt["status"] = 0
    if mutation == "orphan":
        w3.eth.get_block.return_value = {"hash": bytes.fromhex("cc" * 32)}
    registration.reconcile(db_session, product, attempt)
    assert attempt.reason == reason
    assert registration.evidence(db_session, product)["status"] != "verified"


def test_unknown_transaction_stays_pending_and_rpc_outage_preserves_state(
    chain, db_session, monkeypatch
):
    product, attempt, w3, *_ = chain
    w3.eth.get_transaction.side_effect = TransactionNotFound("missing")
    registration.reconcile(db_session, product, attempt)
    assert attempt.status == "submitted"
    monkeypatch.setattr(
        registration, "rpc", MagicMock(side_effect=ConnectionError("secret URL"))
    )
    registration.reconcile(db_session, product, attempt)
    assert attempt.status == "submitted" and attempt.reason == "evidence_unavailable"
    assert "secret" not in str(registration.evidence(db_session, product))


def test_replacement_requires_same_nonce_and_retains_history(chain, client_fixture):
    product, attempt, w3, tx, *_ = chain
    path = f"/products/{product.product_id}/registration"
    assert (
        client_fixture.post(
            path, json={"tx_hash": OTHER, "replaces_tx_hash": HASH}
        ).status_code
        == 200
    )
    history = client_fixture.get(path).json()["attempts"]
    assert history[1]["status"] == "replaced"
    assert history[1]["replaced_by"] == OTHER
    assert history[0]["replaces_tx_hash"] == HASH


def test_unrelated_nonce_cannot_replace_attempt(chain, client_fixture):
    product, attempt, w3, tx, *_ = chain
    w3.eth.get_transaction.side_effect = lambda h: dict(
        tx, nonce=8 if h == OTHER else 7
    )
    path = f"/products/{product.product_id}/registration"
    assert (
        client_fixture.post(
            path, json={"tx_hash": OTHER, "replaces_tx_hash": HASH}
        ).status_code
        == 409
    )
    assert client_fixture.get(path).json()["attempts"][0]["replaced_by"] is None


def test_metadata_requires_indexed_owner_and_contract_evidence(
    chain, client_fixture, db_session
):
    product, attempt, w3, tx, receipt, event, registry = chain
    path = f"/products/{product.product_id}/registration"
    payload = {"tx_hash": OTHER, "operation": "metadata", "metadata_uri": "ipfs://two"}
    assert client_fixture.post(path, json=payload).status_code == 409
    product.registration_status = "indexed"
    db_session.commit()
    assert client_fixture.post(path, json=payload).status_code == 200
    registry.decode_function_input.return_value = (
        SimpleNamespace(fn_name="updateProductMetadata"),
        dict(
            productId=bytes.fromhex(product.on_chain_product_id[2:]),
            newMetadataURI="ipfs://two",
        ),
    )
    registry.events.ProductMetadataUpdated.return_value.process_receipt.return_value = [
        {
            "address": product.registry_address,
            "args": {
                "productId": bytes.fromhex(product.on_chain_product_id[2:]),
                "metadataURI": "ipfs://two",
            },
        }
    ]
    response = client_fixture.post(path + "/reconcile", params={"tx_hash": OTHER})
    assert response.json()["status"] == "indexing"
    db_session.refresh(product)
    assert product.metadata_uri == "ipfs://one"


def test_cancelled_replacement_does_not_register(chain, client_fixture):
    product, attempt, w3, tx, receipt, *_ = chain
    w3.eth.get_transaction.side_effect = lambda h: (
        dict(tx, to=OWNER, input="0x") if h == OTHER else tx
    )
    path = f"/products/{product.product_id}/registration"
    assert (
        client_fixture.post(
            path, json={"tx_hash": OTHER, "replaces_tx_hash": HASH}
        ).status_code
        == 200
    )
    response = client_fixture.post(path + "/reconcile", params={"tx_hash": OTHER})
    assert response.json()["status"] == "failed"
    assert response.json()["reason"] == "transaction_cancelled"


def test_late_submission_of_indexed_registration_is_accepted(
    chain, client_fixture, db_session
):
    product, attempt, *_ = chain
    # The indexer can beat a wallet's submission callback for the same transaction.
    product.registration_status = "indexed"
    product.tx_hash = OTHER
    db_session.commit()
    response = client_fixture.post(
        f"/products/{product.product_id}/registration", json={"tx_hash": OTHER}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "submitted"
    assert (
        client_fixture.post(
            f"/products/{product.product_id}/registration",
            json={"tx_hash": "0x" + "d" * 64},
        ).status_code
        == 409
    )


def test_registration_snapshot_survives_later_metadata_updates(chain, db_session):
    product, attempt, *_ = chain
    product.metadata_uri = "ipfs://later-indexed-value"
    registration.reconcile(db_session, product, attempt)
    assert attempt.status == "indexing"
    assert attempt.reason == "awaiting_indexer"
