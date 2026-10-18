"""Compatibility receipt check; public verification also requires indexed journal evidence."""

from app.services.registration import observe


def verify_registration(product) -> bool:
    if (
        getattr(product, "registration_status", None) != "indexed"
        or not getattr(product, "on_chain_product_id", None)
        or product.block_number <= 0
        or not product.tx_hash
        or len(product.tx_hash) != 66
    ):
        return False
    result = observe(product)
    return result["status"] == "indexing"
