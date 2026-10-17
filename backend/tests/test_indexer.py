"""
Tests for backend/app/services/indexer.py

Covers:
  - bytes32_to_hex / timestamp_to_datetime pure helpers
  - load_indexer_state / save_indexer_state (file I/O)
  - EventIndexer._process_product_registered (new + duplicate)
  - EventIndexer._process_checkpoint_recorded
  - EventIndexer._process_custody_transferred
  - EventIndexer._process_delivery_completed

SessionLocal is patched at app.services.indexer.SessionLocal so the _process_*
methods write to an in-memory SQLite database instead of the real one.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Force SQLite before any app import so config never tries psycopg2.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.database import Base
from app.models.product import Product
from app.models.shipment import Checkpoint, CustodyTransfer, Shipment
from app.services.indexer import (
    EventIndexer,
    bytes32_to_hex,
    load_indexer_state,
    save_indexer_state,
    timestamp_to_datetime,
)

# ---------------------------------------------------------------------------
# In-memory SQLite engine shared across all indexer tests
# ---------------------------------------------------------------------------

_TEST_DB_URL = "sqlite:///:memory:"
_engine = create_engine(
    _TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture(autouse=True)
def _reset_schema():
    """Create all tables before each test and drop them after."""
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


def _make_session():
    """Return a real in-memory session for use inside patched SessionLocal."""
    return _TestingSessionLocal()


# ---------------------------------------------------------------------------
# Shared event dict builders
# ---------------------------------------------------------------------------

_PRODUCT_ID_BYTES = b"\xab" * 32
_TX_HASH_BYTES = bytes.fromhex("cd" * 32)
_MANUFACTURER = "0xABCDEF1234567890ABCDEF1234567890ABCDEF12"
_HANDLER = "0x1111111111111111111111111111111111111111"
_FROM_ADDR = "0x2222222222222222222222222222222222222222"
_TO_ADDR = "0x3333333333333333333333333333333333333333"
_BLOCK = 12345
_TS = 1_000_000_000


def _product_registered_event():
    return {
        "args": {
            "productId": _PRODUCT_ID_BYTES,
            "manufacturer": _MANUFACTURER,
            "name": "TestProduct",
            "timestamp": _TS,
        },
        "blockNumber": _BLOCK,
        "transactionHash": _TX_HASH_BYTES,
    }


def _checkpoint_event():
    return {
        "address": _HANDLER,
        "logIndex": 1,
        "args": {
            "productId": _PRODUCT_ID_BYTES,
            "location": "Warehouse A",
            "status": 1,
            "handler": _HANDLER,
            "timestamp": _TS,
            "notes": "Arrived safely",
        },
        "blockNumber": _BLOCK,
        "transactionHash": _TX_HASH_BYTES,
    }


def _custody_event():
    return {
        "address": _HANDLER,
        "logIndex": 2,
        "args": {
            "productId": _PRODUCT_ID_BYTES,
            "from": _FROM_ADDR,
            "to": _TO_ADDR,
            "timestamp": _TS,
        },
        "blockNumber": _BLOCK,
        "transactionHash": _TX_HASH_BYTES,
    }


def _delivery_event():
    return {
        "args": {
            "productId": _PRODUCT_ID_BYTES,
            "handler": _HANDLER,
            "timestamp": _TS,
        },
        "blockNumber": _BLOCK,
        "transactionHash": _TX_HASH_BYTES,
    }


def _insert_parent_product(session):
    """Insert the Product row that FK-constrained child rows require."""
    product_id_hex = bytes32_to_hex(_PRODUCT_ID_BYTES)
    product = Product(
        product_id=product_id_hex,
        name="Parent Product",
        description=None,
        metadata_uri=None,
        manufacturer_address=_MANUFACTURER,
        registered_at=datetime.fromtimestamp(_TS, tz=timezone.utc),
        block_number=_BLOCK,
        tx_hash=_TX_HASH_BYTES.hex(),
    )
    session.add(product)
    session.commit()
    return product_id_hex


# ---------------------------------------------------------------------------
# Helper: build a patched EventIndexer whose SessionLocal returns a real session
# ---------------------------------------------------------------------------

def _make_indexer_with_session(session):
    """
    Return (indexer, mock_session_local) where SessionLocal() == session.
    The caller is responsible for starting the patch context.
    """
    indexer = EventIndexer(
        rpc_url="http://localhost:8545",
        product_registry_address="0x" + "0" * 40,
        shipment_tracker_address="0x" + "0" * 40,
    )
    return indexer


# ===========================================================================
# 1. bytes32_to_hex
# ===========================================================================

def test_bytes32_to_hex():
    result = bytes32_to_hex(bytes(32))
    assert result.startswith("0x"), "Result must start with '0x'"
    assert len(result) == 66, f"Expected 66 chars, got {len(result)}"


# ===========================================================================
# 2. timestamp_to_datetime
# ===========================================================================

def test_timestamp_to_datetime():
    ts = 1_000_000_000  # 2001-09-09 01:46:40 UTC
    dt = timestamp_to_datetime(ts)
    assert dt.tzinfo is not None, "datetime must be timezone-aware"
    assert dt.tzinfo == timezone.utc, "timezone must be UTC"
    assert dt.year == 2001


# ===========================================================================
# 3. load_indexer_state — no file → default
# ===========================================================================

def test_load_indexer_state_default(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("app.services.indexer.INDEXER_STATE_FILE", state_file)

    from app.core.config import settings
    state = load_indexer_state()

    assert "last_processed_block" in state
    assert state["last_processed_block"] == settings.indexer_start_block


# ===========================================================================
# 4. save + load round-trip
# ===========================================================================

def test_load_and_save_indexer_state(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("app.services.indexer.INDEXER_STATE_FILE", state_file)

    save_indexer_state({"last_processed_block": 999})
    loaded = load_indexer_state()

    assert loaded["last_processed_block"] == 999


# ===========================================================================
# 5. _process_product_registered — new product
# ===========================================================================

def test_process_product_registered_new():
    session = _make_session()
    mock_session_local = MagicMock(return_value=session)

    with patch("app.services.indexer.SessionLocal", mock_session_local):
        indexer = EventIndexer(
            rpc_url="http://localhost:8545",
            product_registry_address="0x" + "0" * 40,
            shipment_tracker_address="0x" + "0" * 40,
        )
        # Mock getProduct contract call
        indexer.product_registry = MagicMock()
        indexer.product_registry.functions.getProduct.return_value.call.return_value = (
            "",
            "ProductName",
            "ManufacturerAddr",
            "A description",
            "ipfs://uri",
        )

        indexer._process_product_registered(_product_registered_event())

    # Verify the row was committed (open a fresh session to read it back)
    verify_session = _make_session()
    products = verify_session.query(Product).all()
    verify_session.close()

    assert len(products) == 1
    assert products[0].name == "TestProduct"
    assert products[0].description == "A description"
    assert products[0].metadata_uri == "ipfs://uri"
    assert products[0].manufacturer_address == _MANUFACTURER
    assert products[0].block_number == _BLOCK


# ===========================================================================
# 6. _process_product_registered — duplicate → no second row
# ===========================================================================

def test_process_product_registered_existing():
    # Pre-insert a product with the same product_id
    setup_session = _make_session()
    product_id_hex = bytes32_to_hex(_PRODUCT_ID_BYTES)
    existing = Product(
        product_id=product_id_hex,
        name="Already Here",
        description=None,
        metadata_uri=None,
        manufacturer_address=_MANUFACTURER,
        registered_at=datetime.fromtimestamp(_TS, tz=timezone.utc),
        block_number=_BLOCK,
        tx_hash=_TX_HASH_BYTES.hex(),
    )
    setup_session.add(existing)
    setup_session.commit()
    setup_session.close()

    # Now run the indexer — it should detect the duplicate and skip
    session = _make_session()
    mock_session_local = MagicMock(return_value=session)

    with patch("app.services.indexer.SessionLocal", mock_session_local):
        indexer = EventIndexer(
            rpc_url="http://localhost:8545",
            product_registry_address="0x" + "0" * 40,
            shipment_tracker_address="0x" + "0" * 40,
        )
        indexer.product_registry = MagicMock()
        indexer.product_registry.functions.getProduct.return_value.call.return_value = (
            "",
            "ProductName",
            "ManufacturerAddr",
            "desc",
            "ipfs://uri",
        )

        indexer._process_product_registered(_product_registered_event())

    verify_session = _make_session()
    count = verify_session.query(Product).count()
    verify_session.close()

    assert count == 1, "Duplicate product must not be inserted"


# ===========================================================================
# 7. _process_checkpoint_recorded
# ===========================================================================

def test_process_checkpoint_recorded():
    # Insert parent product first (FK constraint)
    setup_session = _make_session()
    _insert_parent_product(setup_session)
    setup_session.close()

    session = _make_session()
    mock_session_local = MagicMock(return_value=session)

    with patch("app.services.indexer.SessionLocal", mock_session_local):
        indexer = EventIndexer(
            rpc_url="http://localhost:8545",
            product_registry_address="0x" + "0" * 40,
            shipment_tracker_address="0x" + "0" * 40,
        )
        indexer._process_checkpoint_recorded(_checkpoint_event())

    verify_session = _make_session()
    checkpoints = verify_session.query(Checkpoint).all()
    verify_session.close()

    assert len(checkpoints) == 1
    assert checkpoints[0].location == "Warehouse A"
    assert checkpoints[0].status == "1"
    assert checkpoints[0].handler_address == _HANDLER
    assert checkpoints[0].notes == "Arrived safely"
    assert checkpoints[0].block_number == _BLOCK


# ===========================================================================
# 8. _process_custody_transferred
# ===========================================================================

def test_process_custody_transferred():
    setup_session = _make_session()
    _insert_parent_product(setup_session)
    setup_session.close()

    session = _make_session()
    mock_session_local = MagicMock(return_value=session)

    with patch("app.services.indexer.SessionLocal", mock_session_local):
        indexer = EventIndexer(
            rpc_url="http://localhost:8545",
            product_registry_address="0x" + "0" * 40,
            shipment_tracker_address="0x" + "0" * 40,
        )
        indexer._process_custody_transferred(_custody_event())

    verify_session = _make_session()
    transfers = verify_session.query(CustodyTransfer).all()
    verify_session.close()

    assert len(transfers) == 1
    assert transfers[0].from_address == _FROM_ADDR
    assert transfers[0].to_address == _TO_ADDR
    assert transfers[0].block_number == _BLOCK


# ===========================================================================
# 9. _process_delivery_completed
# ===========================================================================

def test_process_delivery_completed():
    setup_session = _make_session()
    _insert_parent_product(setup_session)
    setup_session.close()

    session = _make_session()
    mock_session_local = MagicMock(return_value=session)

    with patch("app.services.indexer.SessionLocal", mock_session_local):
        indexer = EventIndexer(
            rpc_url="http://localhost:8545",
            product_registry_address="0x" + "0" * 40,
            shipment_tracker_address="0x" + "0" * 40,
        )
        event = _checkpoint_event()
        event["args"]["status"] = 3
        indexer._process_checkpoint_recorded(event)
        indexer._process_delivery_completed(_delivery_event())

    verify_session = _make_session()
    checkpoints = verify_session.query(Checkpoint).all()
    verify_session.close()

    assert len(checkpoints) == 1
    assert checkpoints[0].status == "3"
    assert checkpoints[0].location == "Warehouse A"
    assert checkpoints[0].handler_address == _HANDLER
    assert checkpoints[0].block_number == _BLOCK


@pytest.mark.parametrize('model,event_factory,method', [
    (Checkpoint, _checkpoint_event, '_process_checkpoint_recorded'),
    (CustodyTransfer, _custody_event, '_process_custody_transferred'),
])
def test_history_replay_in_a_new_indexer_does_not_duplicate(model, event_factory, method):
    with _make_session() as db:
        _insert_parent_product(db)
    with patch('app.services.indexer.SessionLocal', side_effect=_make_session):
        for _ in range(2):
            indexer = EventIndexer(shipment_tracker_address=_HANDLER)
            getattr(indexer, method)(event_factory())
    with _make_session() as db:
        rows = db.query(model).all()
        assert len(rows) == 1
        assert rows[0].source_event_id.endswith(':' + str(event_factory()['logIndex']))


@pytest.mark.parametrize('model,event_factory,method', [
    (Checkpoint, _checkpoint_event, '_process_checkpoint_recorded'),
    (CustodyTransfer, _custody_event, '_process_custody_transferred'),
])
def test_distinct_logs_in_one_transaction_are_preserved(model, event_factory, method):
    with _make_session() as db:
        _insert_parent_product(db)
    first = event_factory()
    second = event_factory()
    second['logIndex'] += 1
    with patch('app.services.indexer.SessionLocal', side_effect=_make_session):
        indexer = EventIndexer(shipment_tracker_address=_HANDLER)
        getattr(indexer, method)(first)
        getattr(indexer, method)(second)
    with _make_session() as db:
        assert db.query(model).count() == 2


@pytest.mark.parametrize('event_factory,method', [
    (_checkpoint_event, '_process_checkpoint_recorded'),
    (_custody_event, '_process_custody_transferred'),
])
def test_history_event_without_log_identity_is_rejected(event_factory, method):
    event = event_factory()
    del event['logIndex']
    indexer = EventIndexer(shipment_tracker_address=_HANDLER)
    with pytest.raises(ValueError, match='log index'):
        getattr(indexer, method)(event)


def test_checkpoint_replay_does_not_regress_latest_shipment_status():
    with _make_session() as db:
        product_id = _insert_parent_product(db)
        db.add(Shipment(shipment_id='SHIP-REPLAY', product_id=product_id,
                        origin='Factory', destination='Depot', status='0'))
        db.commit()
    first = _checkpoint_event()
    delivered = _checkpoint_event()
    delivered['logIndex'] += 1
    delivered['args']['status'] = 3
    with patch('app.services.indexer.SessionLocal', side_effect=_make_session):
        indexer = EventIndexer(shipment_tracker_address=_HANDLER)
        indexer._process_checkpoint_recorded(first)
        indexer._process_checkpoint_recorded(delivered)
        indexer._process_checkpoint_recorded(first)
    with _make_session() as db:
        assert db.query(Checkpoint).count() == 2
        assert db.query(Shipment).one().status == '3'
