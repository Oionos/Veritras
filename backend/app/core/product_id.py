def canonical_product_id(value: str) -> bytes:
    if value.startswith("0x") and len(value) == 66:
        return bytes.fromhex(value[2:])
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > 32:
        raise ValueError("Product ID must fit bytes32")
    return encoded.ljust(32, b"\x00")
