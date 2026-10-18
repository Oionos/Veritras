"""Stable UTF-8/right-padded bytes32 IDs; hexadecimal values are never re-encoded."""

import re


def canonical_product_id(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("Product ID must be a nonempty string")
    if value.lower().startswith("0x"):
        if not re.fullmatch(r"0[xX][0-9a-fA-F]{64}", value):
            raise ValueError("Hex product ID must contain exactly 32 bytes")
        result = bytes.fromhex(value[2:])
    else:
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeError:
            raise ValueError("Product ID must contain valid Unicode") from None
        if not encoded or len(encoded) > 32 or b"\x00" in encoded:
            raise ValueError("Text product ID must fit bytes32 without NUL characters")
        result = encoded.ljust(32, b"\x00")
    if result == bytes(32):
        raise ValueError("Zero product ID is not accepted by the contracts")
    return result


def canonical_hex(value: str) -> str:
    return "0x" + canonical_product_id(value).hex()
