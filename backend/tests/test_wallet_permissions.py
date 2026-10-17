from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from unittest.mock import MagicMock

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import HTTPException
from jose import jwt
from siwe import SiweMessage
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.auth import create_access_token, issue_challenge, verify_challenge
from app.core.config import Settings, settings
from app.core.database import Base
from app.models.auth import AuthChallenge
from app.models.product import Product

ORIGIN = "http://localhost:5173"


def begin_login(client, wallet):
    response = client.post("/auth/challenge", headers={"Origin": ORIGIN}, json={"address": wallet.address})
    assert response.status_code == 200
    message = response.json()["message"]
    signature = wallet.sign_message(encode_defunct(text=message)).signature.hex()
    return message, signature


def finish_login(client, message, signature, origin=ORIGIN):
    return client.post("/auth/verify", headers={"Origin": origin}, json={"message": message, "signature": signature})


def headers(wallet):
    return {"Authorization": "Bearer " + create_access_token(wallet.address)}


def test_signed_login_creates_owned_draft_and_shipment(client_fixture):
    wallet = Account.create()
    message, signature = begin_login(client_fixture, wallet)
    response = finish_login(client_fixture, message, signature)
    assert response.status_code == 200
    auth = {"Authorization": "Bearer " + response.json()["access_token"]}
    draft = client_fixture.post("/products/", headers=auth, json={"name": "Owned item"})
    assert draft.status_code == 200
    assert draft.json()["manufacturer_address"].lower() == wallet.address.lower()
    assert draft.json()["owner_address"] == wallet.address.lower()
    assert draft.json()["ownership_source"] == "signed_draft"
    result = client_fixture.post("/shipments/", headers=auth, json={"product_id": draft.json()["product_id"], "origin": "Factory", "destination": "Depot"})
    assert result.status_code == 200


@pytest.mark.parametrize("path,body", [
    ("/products/", {"name": "Anonymous"}),
    ("/shipments/", {"product_id": "PROD-1", "origin": "Factory", "destination": "Depot"}),
])
def test_anonymous_writes_are_unauthorized(client_fixture, path, body):
    client_fixture.headers.pop("Authorization", None)
    response = client_fixture.post(path, json=body)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_another_wallet_cannot_edit_owned_records(client_fixture):
    owner, other = Account.create(), Account.create()
    draft = client_fixture.post("/products/", headers=headers(owner), json={"name": "Owned item"}).json()
    assert client_fixture.put(f"/products/{draft['product_id']}", headers=headers(other), json={"name": "Stolen"}).status_code == 403
    body = {"product_id": draft["product_id"], "origin": "Factory", "destination": "Depot"}
    assert client_fixture.post("/shipments/", headers=headers(other), json=body).status_code == 403
    shipment = client_fixture.post("/shipments/", headers=headers(owner), json=body).json()
    assert client_fixture.put(f"/shipments/{shipment['shipment_id']}", headers=headers(other), json={"notes": "Stolen"}).status_code == 403


def test_manufacturer_and_status_cannot_be_forged(client_fixture):
    owner, other = Account.create(), Account.create()
    assert client_fixture.post("/products/", headers=headers(owner), json={"name": "Forged", "manufacturer_address": other.address}).status_code == 403
    draft = client_fixture.post("/products/", headers=headers(owner), json={"name": "Owned"}).json()
    assert client_fixture.put(f"/products/{draft['product_id']}", headers=headers(owner), json={"manufacturer_address": other.address}).status_code == 422
    assert client_fixture.post("/shipments/", headers=headers(owner), json={"product_id": draft["product_id"], "origin": "Factory", "destination": "Depot", "status": "3"}).status_code == 422


def test_legacy_manufacturer_does_not_grant_ownership(client_fixture, db_session):
    wallet = Account.create()
    db_session.add(Product(product_id="LEGACY", name="Legacy", manufacturer_address=wallet.address, registered_at=datetime.now(), block_number=0, tx_hash="0x"))
    db_session.commit()
    assert client_fixture.put("/products/LEGACY", headers=headers(wallet), json={"name": "Claimed"}).status_code == 403
    client_fixture.headers.pop("Authorization", None)
    assert client_fixture.get("/products/LEGACY").status_code == 200
    assert client_fixture.get("/products/LEGACY/verify").status_code == 200


def test_confirmed_product_fields_are_immutable(client_fixture, db_session):
    wallet = Account.create()
    draft = client_fixture.post("/products/", headers=headers(wallet), json={"name": "Registered"}).json()
    row = db_session.scalar(select(Product).where(Product.product_id == draft["product_id"]))
    row.ownership_source = "chain_event"
    row.block_number = 100
    row.tx_hash = "0x" + "a" * 64
    db_session.commit()
    assert client_fixture.put(f"/products/{row.product_id}", headers=headers(wallet), json={"name": "Changed"}).status_code == 409


@pytest.mark.parametrize("registered,expected", [(True, 409), (False, 200), (None, 503)])
def test_unindexed_registration_is_checked_before_draft_edits(client_fixture, monkeypatch, registered, expected):
    import app.core.permissions as permissions
    wallet = Account.create()
    draft = client_fixture.post("/products/", headers=headers(wallet), json={"name": "Draft"}).json()
    monkeypatch.setattr(settings, "sepolia_rpc_url", "https://rpc.example/private-placeholder")
    monkeypatch.setattr(settings, "product_registry_contract", wallet.address)
    web3 = MagicMock()
    web3.return_value.eth.chain_id = settings.chain_id
    registration = web3.return_value.eth.contract.return_value.functions.isProductRegistered.return_value.call
    if registered is None:
        registration.side_effect = ConnectionError("private-placeholder")
    else:
        registration.return_value = registered
    monkeypatch.setattr(permissions, "Web3", web3)
    response = client_fixture.put(f"/products/{draft['product_id']}", headers=headers(wallet), json={"name": "Edited"})
    assert response.status_code == expected
    assert "private-placeholder" not in response.text


@pytest.mark.parametrize("old,new", [
    ("localhost:5173 wants", "evil.example wants"),
    ("URI: http://localhost:5173", "URI: https://evil.example"),
    ("Chain ID: 11155111", "Chain ID: 1"),
    ("Sign in to Veritras", "Sign in somewhere else"),
])
def test_wrong_scope_does_not_consume_challenge(client_fixture, old, new):
    wallet = Account.create()
    message, signature = begin_login(client_fixture, wallet)
    changed = message.replace(old, new)
    assert changed != message
    changed_signature = wallet.sign_message(encode_defunct(text=changed)).signature.hex()
    assert finish_login(client_fixture, changed, changed_signature).status_code == 401
    assert finish_login(client_fixture, message, signature).status_code == 200


def test_invalid_signature_does_not_consume_and_valid_signature_cannot_replay(client_fixture):
    wallet, other = Account.create(), Account.create()
    message, signature = begin_login(client_fixture, wallet)
    invalid = other.sign_message(encode_defunct(text=message)).signature.hex()
    assert finish_login(client_fixture, message, invalid).status_code == 401
    response = finish_login(client_fixture, message, signature)
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert finish_login(client_fixture, message, signature).status_code == 401


def test_expired_challenge_is_rejected(client_fixture, db_session):
    wallet = Account.create()
    message, signature = begin_login(client_fixture, wallet)
    row = db_session.scalar(select(AuthChallenge))
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert finish_login(client_fixture, message, signature).status_code == 401


def test_wrong_request_origin_is_rejected(client_fixture):
    wallet = Account.create()
    assert client_fixture.post("/auth/challenge", headers={"Origin": "https://evil.example"}, json={"address": wallet.address}).status_code == 403
    message, signature = begin_login(client_fixture, wallet)
    assert finish_login(client_fixture, message, signature, origin="https://evil.example").status_code == 401


@pytest.mark.parametrize("claim,value", [
    ("exp", 1), ("iss", "another-api"), ("aud", "another-app"),
    ("sub", "not-a-wallet"), ("chain_id", 1), ("iat", 9999999999),
])
def test_wrong_token_claims_are_rejected(client_fixture, claim, value):
    wallet = Account.create()
    payload = jwt.get_unverified_claims(create_access_token(wallet.address))
    payload[claim] = value
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
    assert client_fixture.post("/products/", headers={"Authorization": "Bearer " + token}, json={"name": "Unauthorized"}).status_code == 401


@pytest.mark.parametrize("claim", ["exp", "iat", "nbf", "sub", "iss", "aud", "jti"])
def test_required_token_claims_cannot_be_missing(client_fixture, claim):
    payload = jwt.get_unverified_claims(create_access_token(Account.create().address))
    payload.pop(claim)
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
    assert client_fixture.post("/products/", headers={"Authorization": "Bearer " + token}, json={"name": "Unauthorized"}).status_code == 401


def test_render_cannot_use_the_development_signing_key(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, jwt_secret_key="dev-secret-change-in-production")


def test_concurrent_challenge_consumption_has_one_winner(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrency.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    wallet = Account.create()
    with Session(engine) as db:
        data = issue_challenge(db, ORIGIN, wallet.address)
    signature = wallet.sign_message(encode_defunct(text=data["message"])).signature.hex()
    barrier = Barrier(2)
    original = SiweMessage.verify

    def synchronized_verify(self, *args, **kwargs):
        original(self, *args, **kwargs)
        barrier.wait(timeout=10)

    monkeypatch.setattr(SiweMessage, "verify", synchronized_verify)

    def consume(_):
        with Session(engine) as db:
            request = Request({"type": "http", "headers": [(b"origin", ORIGIN.encode())]})
            try:
                verify_challenge(db, request, data["message"], signature)
                return 200
            except HTTPException as error:
                return error.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(consume, range(2))) == [200, 401]
    finally:
        engine.dispose()
