from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import verification


@pytest.fixture
def evidence(monkeypatch):
    registry = "0x" + "1" * 40
    manufacturer = "0x" + "2" * 40
    product = SimpleNamespace(product_id="PROD-TEST", name="Widget", manufacturer_address=manufacturer,
                              block_number=10, tx_hash="0x" + "a" * 64)
    receipt = {"status": 1, "to": registry, "blockNumber": 10}
    event = {"address": registry, "args": {"productId": b"PROD-TEST".ljust(32, b"\x00"),
                                             "manufacturer": manufacturer, "name": "Widget"}}
    w3 = MagicMock()
    w3.eth.chain_id = 11155111
    w3.to_checksum_address.return_value = registry
    w3.eth.get_transaction_receipt.return_value = receipt
    w3.eth.contract.return_value.events.ProductRegistered.return_value.process_receipt.return_value = [event]
    provider = MagicMock(return_value=w3)
    monkeypatch.setattr(verification, "Web3", provider)
    monkeypatch.setattr(verification.settings, "sepolia_rpc_url", "https://testing.invalid")
    monkeypatch.setattr(verification.settings, "product_registry_contract", registry)
    monkeypatch.setattr(verification.settings, "chain_id", 11155111)
    return product, receipt, event, w3, provider


def test_matching_receipt_and_event_verify(evidence):
    product, *_ = evidence
    assert verification.verify_registration(product) is True


@pytest.mark.parametrize("field,value", [("status", 0), ("to", "0x" + "3" * 40), ("blockNumber", 11)])
def test_wrong_or_failed_receipt_does_not_verify(evidence, field, value):
    product, receipt, *_ = evidence
    receipt[field] = value
    assert verification.verify_registration(product) is False


@pytest.mark.parametrize("field,value", [("productId", b"wrong"), ("manufacturer", "0x" + "3" * 40), ("name", "Other item")])
def test_wrong_event_does_not_verify(evidence, field, value):
    product, _, event, *_ = evidence
    event["args"][field] = value
    assert verification.verify_registration(product) is False


def test_draft_never_requests_blockchain_evidence(evidence):
    product, _, _, _, provider = evidence
    product.block_number = 0
    assert verification.verify_registration(product) is False
    provider.assert_not_called()


def test_wrong_rpc_chain_is_unavailable(evidence):
    product, _, _, w3, _ = evidence
    w3.eth.chain_id = 1
    with pytest.raises(ConnectionError):
        verification.verify_registration(product)
