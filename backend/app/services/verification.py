"""Receipt-backed registration checks; database presence alone is not proof."""

from web3 import Web3
from web3.logs import DISCARD

from app.core.config import settings
from app.core.product_id import canonical_product_id
from app.services.indexer import load_abi


def verify_registration(product) -> bool:
    if product.block_number <= 0 or not product.tx_hash or len(product.tx_hash) != 66:
        return False
    if not settings.sepolia_rpc_url or not settings.product_registry_contract:
        raise ConnectionError("Registration evidence is unavailable")
    w3 = Web3(Web3.HTTPProvider(settings.sepolia_rpc_url, request_kwargs={"timeout": settings.indexer_rpc_timeout}))
    if w3.eth.chain_id != settings.chain_id:
        raise ConnectionError("Configured chain is unavailable")
    registry = w3.to_checksum_address(settings.product_registry_contract)
    receipt = w3.eth.get_transaction_receipt(product.tx_hash)
    if receipt["status"] != 1 or (receipt.get("to") or "").lower() != registry.lower():
        return False
    if receipt["blockNumber"] != product.block_number:
        return False
    try:
        canonical_id = canonical_product_id(product.product_id)
    except ValueError:
        return False
    contract = w3.eth.contract(address=registry, abi=load_abi("ProductRegistry"))
    return any(
        log["address"].lower() == registry.lower()
        and bytes(log["args"]["productId"]) == canonical_id
        and log["args"]["manufacturer"].lower() == product.manufacturer_address.lower()
        and log["args"]["name"] == product.name
        for log in contract.events.ProductRegistered().process_receipt(receipt, errors=DISCARD)
    )
