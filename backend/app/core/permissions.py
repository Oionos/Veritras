from fastapi import HTTPException
from web3 import Web3

from app.core.config import settings
from app.core.product_id import canonical_product_id
from app.models.product import Product


def require_product_owner(product: Product, address: str):
    if (product.ownership_source not in {"signed_draft", "chain_event"}
            or not product.owner_address
            or product.owner_address.lower() != address.lower()):
        raise HTTPException(status_code=403, detail="Product ownership is not established for this wallet")


def require_editable_draft(product: Product, address: str):
    require_product_owner(product, address)
    if product.ownership_source != "signed_draft" or product.block_number != 0 or product.tx_hash != "0x":
        raise HTTPException(status_code=409, detail="Registered product fields must be updated through the contract")
    # Hosted indexing can be disabled or behind the chain. A draft-looking SQL
    # row is insufficient to conclude its registration fields are still mutable.
    if not settings.sepolia_rpc_url or not settings.product_registry_contract:
        if settings.is_hosted:
            raise HTTPException(status_code=503, detail="Registration status is unavailable; draft edits are paused")
        return
    try:
        w3 = Web3(Web3.HTTPProvider(settings.sepolia_rpc_url, request_kwargs={"timeout": settings.indexer_rpc_timeout}))
        if w3.eth.chain_id != settings.chain_id:
            raise ValueError("Wrong chain")
        registry = w3.eth.contract(
            address=Web3.to_checksum_address(settings.product_registry_contract),
            abi=[{"type": "function", "name": "isProductRegistered", "stateMutability": "view",
                  "inputs": [{"name": "productId", "type": "bytes32"}],
                  "outputs": [{"name": "", "type": "bool"}]}],
        )
        registered = registry.functions.isProductRegistered(canonical_product_id(product.product_id)).call()
    except Exception:
        raise HTTPException(status_code=503, detail="Registration status is unavailable; draft edits are paused") from None
    if registered:
        raise HTTPException(status_code=409, detail="Registered product fields must be updated through the contract")
