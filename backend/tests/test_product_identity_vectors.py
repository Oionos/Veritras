import json
from pathlib import Path
import pytest
from app.core.product_id import canonical_hex

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures/product-ids.json").read_text()
)


@pytest.mark.parametrize("vector", VECTORS)
def test_shared_identity_conversion(vector):
    value = vector.get("input", "".join(chr(c) for c in vector.get("codepoints", [])))
    if vector.get("error"):
        with pytest.raises((ValueError, UnicodeError)):
            canonical_hex(value)
    else:
        assert canonical_hex(value) == vector["expected"]
        assert canonical_hex(vector["expected"]) == vector["expected"]
