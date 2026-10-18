"""Atomic indexing and canonical replay; no network or production credentials."""

import copy
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from sqlalchemy import create_engine, event as sql_event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.core.database import Base
from app.models.chain import ChainBlock, ChainEvent, IndexedProduct, IndexerCursor
from app.models.product import Product
from app.models.shipment import Checkpoint, CustodyTransfer, Shipment
from app.services.indexer import (
    EventIndexer,
    IndexerBusy,
    ReconciliationRequired,
    bytes32_to_hex,
    timestamp_to_datetime,
)

REGISTRY, TRACKER, OWNER, HANDLER = ["0x" + str(i) * 40 for i in range(1, 5)]
KEY = b"PROD-TEST".ljust(32, b"\x00")


def h(n):
    return n.to_bytes(32, "big")


def log(kind, block, index=0, **args):
    values = {"productId": KEY}
    if kind == "ProductRegistered":
        values.update(manufacturer=OWNER, name="Widget", timestamp=1000)
    elif kind == "CheckpointRecorded":
        values.update(
            location="Factory",
            handler=OWNER,
            status=0,
            timestamp=1000 + block,
            notes="",
        )
    elif kind == "CustodyTransferred":
        values.update({"from": OWNER, "to": HANDLER, "timestamp": 1000 + block})
    elif kind == "DeliveryCompleted":
        values.update(handler=HANDLER, timestamp=1000 + block)
    else:
        values.update(metadataURI="ipfs://updated")
    values.update(args)
    return dict(
        event=kind,
        address=REGISTRY if kind.startswith("Product") else TRACKER,
        args=values,
        blockNumber=block,
        blockHash=h(block),
        transactionHash=h(block * 100),
        transactionIndex=0,
        logIndex=index,
        registration_details={
            "description": "Description",
            "metadataURI": "ipfs://initial",
        },
    )


@pytest.fixture(params=["sqlite", "postgres"])
def stack(tmp_path, monkeypatch, request):
    if request.param == "postgres":
        url = os.environ.get("INDEXER_TEST_DATABASE_URL")
        if not url:
            pytest.skip("Dedicated Postgres regression database not configured")
        parsed = make_url(url)
        assert parsed.database == "veritras_indexer_regression"
        assert parsed.host in ("localhost", "127.0.0.1", "postgres")
        engine = create_engine(url)
    else:
        engine = create_engine(f'sqlite:///{tmp_path / "indexer.db"}')

        @sql_event.listens_for(engine, "connect")
        def foreign_keys(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, autoflush=False)
    monkeypatch.setattr("app.services.indexer.SessionLocal", sessions)
    for name, value in [
        ("indexer_confirmations", 0),
        ("indexer_start_block", 0),
        ("indexer_batch_size", 10),
    ]:
        monkeypatch.setattr(settings, name, value)
    chain = SimpleNamespace(
        head=5,
        hashes={i: h(i) for i in range(20)},
        events=[log("ProductRegistered", 1)],
    )

    def new():
        worker = EventIndexer(
            product_registry_address=REGISTRY, shipment_tracker_address=TRACKER
        )
        worker.w3 = SimpleNamespace(
            eth=SimpleNamespace(
                get_block=lambda n: {"number": n, "hash": chain.hashes[n]}
            )
        )
        worker._fetch_events = lambda start, end: sorted(
            [
                copy.deepcopy(e)
                for e in chain.events
                if start <= e["blockNumber"] <= end
            ],
            key=lambda e: (e["blockNumber"], e["transactionIndex"], e["logIndex"]),
        )
        poll = worker.poll_once

        def run():
            worker.w3.eth.block_number = chain.head
            return poll()

        worker.poll_once = run
        return worker

    yield SimpleNamespace(engine=engine, sessions=sessions, chain=chain, new=new)
    Base.metadata.drop_all(engine)
    engine.dispose()


def draft(stack):
    with stack.sessions() as db:
        db.add(
            Product(
                product_id="PROD-TEST",
                name="Draft name",
                description="Draft description",
                manufacturer_address=OWNER,
                owner_address=OWNER,
                ownership_source="signed_draft",
                registered_at=datetime(2026, 1, 1),
                block_number=0,
                tx_hash="0x",
            )
        )
        db.flush()
        db.add(
            Shipment(
                shipment_id="SHIP-TEST",
                product_id="PROD-TEST",
                origin="Factory",
                destination="Depot",
                notes="Keep planning",
                status="0",
            )
        )
        db.commit()


def counts(stack):
    with stack.sessions() as db:
        return tuple(
            db.query(m).count()
            for m in (Product, Checkpoint, CustodyTransfer, ChainEvent)
        )


def fork(stack, start):
    for n in range(start, stack.chain.head + 1):
        stack.chain.hashes[n] = h(1000 + n)


def test_helpers():
    assert bytes32_to_hex(bytes(32)) == "0x" + "00" * 32
    assert timestamp_to_datetime(1000).tzinfo == timezone.utc


def test_atomic_journey_and_restart(stack):
    draft(stack)
    stack.chain.events += [
        log("CheckpointRecorded", 2),
        log("CustodyTransferred", 3),
        log("DeliveryCompleted", 4),
        log("CheckpointRecorded", 4, 1, status=3, handler=HANDLER),
    ]
    first = stack.new()
    first.poll_once()
    assert counts(stack) == (1, 2, 1, 5)
    stack.new().poll_once()
    assert counts(stack) == (1, 2, 1, 5)
    with stack.sessions() as db:
        assert db.get(IndexerCursor, first.scope).last_processed_block == 5
        state = db.query(IndexedProduct).one()
        assert state.product_id == "PROD-TEST" and state.current_handler == HANDLER
        shipment = db.query(Shipment).one()
        assert (
            shipment.status == "3"
            and shipment.current_handler == HANDLER
            and shipment.notes == "Keep planning"
        )


def test_projection_failure_rolls_back_entire_batch(stack):
    worker = stack.new()
    stack.chain.events += [log("CheckpointRecorded", 2)]
    original = worker._project

    def failing(db, row):
        original(db, row)
        if row.event_type == "CheckpointRecorded":
            raise RuntimeError("persistence failure")

    worker._project = failing
    with pytest.raises(RuntimeError):
        worker.poll_once()
    assert counts(stack) == (0, 0, 0, 0)
    with stack.sessions() as db:
        assert db.query(IndexerCursor).count() == 0
    worker._project = original
    worker.poll_once()
    assert counts(stack) == (1, 1, 0, 2)


def test_commit_failure_preserves_previous_cursor(stack):
    worker = stack.new()
    worker.poll_once()
    stack.chain.head = 6
    stack.chain.events.append(log("CheckpointRecorded", 6))

    @sql_event.listens_for(stack.sessions, "before_commit")
    def fail(_):
        raise RuntimeError("interrupted commit")

    with pytest.raises(RuntimeError):
        worker.poll_once()
    sql_event.remove(stack.sessions, "before_commit", fail)
    with stack.sessions() as db:
        assert db.get(IndexerCursor, worker.scope).last_processed_block == 5
        assert db.query(Checkpoint).count() == 0
    assert worker.last_processed_block == 5
    worker.poll_once()
    assert counts(stack) == (1, 1, 0, 2)


def test_reorg_rebuilds_custody_metadata_delivery_and_retains_audit(stack):
    draft(stack)
    stack.chain.events += [
        log("CheckpointRecorded", 2),
        log("CustodyTransferred", 3),
        log("ProductMetadataUpdated", 4),
        log("DeliveryCompleted", 4, 1),
        log("CheckpointRecorded", 4, 2, status=3, handler=HANDLER),
    ]
    worker = stack.new()
    worker.poll_once()
    fork(stack, 3)
    replacement = log("CheckpointRecorded", 3, status=1)
    replacement.update(blockHash=stack.chain.hashes[3], transactionHash=h(900))
    stack.chain.events = stack.chain.events[:2] + [replacement]
    stack.chain.head = 6
    worker.poll_once()
    with stack.sessions() as db:
        assert (
            db.query(Checkpoint).count() == 2 and db.query(CustodyTransfer).count() == 0
        )
        assert (
            db.query(Shipment).one().status == "1"
            and db.query(Shipment).one().notes == "Keep planning"
        )
        assert db.query(IndexedProduct).one().current_handler == OWNER
        assert db.query(Product).one().metadata_uri == "ipfs://initial"
        assert db.query(ChainEvent).filter_by(canonical=False).count() == 4
        assert db.get(IndexerCursor, worker.scope).last_processed_block == 6
    assert worker.last_reorg_ancestor == 2


def test_registration_orphan_restores_draft_and_reincluded_transaction_is_once(stack):
    draft(stack)
    worker = stack.new()
    worker.poll_once()
    original = copy.deepcopy(stack.chain.events[0])
    fork(stack, 1)
    stack.chain.events = []
    worker.poll_once()
    with stack.sessions() as db:
        product = db.query(Product).one()
        assert (
            product.name == "Draft name" and product.description == "Draft description"
        )
        assert product.block_number == 0 and product.ownership_source == "signed_draft"
    original.update(blockNumber=6, blockHash=h(6))
    stack.chain.events = [original]
    stack.chain.head = 6
    worker.poll_once()
    worker.poll_once()
    with stack.sessions() as db:
        assert db.query(Product).one().block_number == 6
        assert db.query(ChainEvent).filter_by(canonical=True).count() == 1
        assert db.query(ChainEvent).filter_by(canonical=False).count() == 1


def test_chain_only_orphan_keeps_url_without_ownership_or_evidence(stack):
    worker = stack.new()
    worker.poll_once()
    fork(stack, 1)
    stack.chain.events = []
    worker.poll_once()
    with stack.sessions() as db:
        product = db.query(Product).one()
        assert (
            product.product_id == bytes32_to_hex(KEY)
            and product.block_number == 0
            and product.owner_address is None
        )


def test_no_ancestor_stops_without_mutation(stack):
    worker = stack.new()
    worker.poll_once()
    before = counts(stack)
    fork(stack, 0)
    with pytest.raises(ReconciliationRequired, match="ancestor"):
        worker.poll_once()
    assert counts(stack) == before


def test_reorg_rebuild_failure_rolls_back_flags_and_cursor(stack):
    worker = stack.new()
    stack.chain.events += [
        log("CheckpointRecorded", 2),
        log("CheckpointRecorded", 4, status=1),
    ]
    worker.poll_once()
    before = counts(stack)
    fork(stack, 4)
    stack.chain.events = stack.chain.events[:2]

    def fail(*_):
        raise RuntimeError("rebuild interrupted")

    worker._project = fail
    with pytest.raises(RuntimeError):
        worker.poll_once()
    assert counts(stack) == before
    with stack.sessions() as db:
        assert db.query(ChainEvent).filter_by(canonical=False).count() == 0
        assert db.get(IndexerCursor, worker.scope).last_processed_block == 5


def test_confirmations_and_empty_ranges(stack, monkeypatch):
    monkeypatch.setattr(settings, "indexer_confirmations", 2)
    worker = stack.new()
    stack.chain.events.append(log("CheckpointRecorded", 4))
    worker.poll_once()
    assert (
        worker.last_processed_block == 3
        and worker.target_head == 3
        and counts(stack) == (1, 0, 0, 1)
    )
    worker.running = True
    worker._last_success_monotonic = __import__("time").monotonic()
    assert (
        worker.health()["status"] == "current" and worker.health()["confirmations"] == 2
    )
    stack.chain.head = 7
    worker.poll_once()
    assert worker.last_processed_block == 5 and counts(stack) == (1, 1, 0, 2)


def test_deployment_start_is_inclusive_and_configuration_changes_fail(
    stack, monkeypatch
):
    monkeypatch.setattr(settings, "indexer_start_block", 1)
    stack.chain.events = [log("ProductRegistered", 2)]
    worker = stack.new()
    worker.poll_once()
    assert counts(stack)[0] == 1
    monkeypatch.setattr(settings, "indexer_start_block", 2)
    with pytest.raises(ReconciliationRequired, match="anchor changed"):
        worker.poll_once()


def test_stale_rpc_head_never_deletes_data(stack):
    worker = stack.new()
    worker.poll_once()
    stack.chain.head = 4
    with pytest.raises(ReconciliationRequired, match="behind"):
        worker.poll_once()
    assert counts(stack)[0] == 1


def test_inconsistent_block_response_rolls_back(stack):
    stack.chain.events[0]["blockHash"] = h(500)
    with pytest.raises(RuntimeError, match="changed"):
        stack.new().poll_once()
    assert counts(stack) == (0, 0, 0, 0)


def test_legacy_unattributed_history_needs_review(stack):
    draft(stack)
    with stack.sessions() as db:
        db.add(
            Checkpoint(
                product_id="PROD-TEST",
                location="Factory",
                status="0",
                handler_address=OWNER,
                timestamp=datetime(2026, 1, 1),
                block_number=1,
                tx_hash="0xlegacy",
            )
        )
        db.commit()
    with pytest.raises(ReconciliationRequired, match="Legacy history"):
        stack.new().poll_once()
    assert counts(stack) == (1, 1, 0, 0)


def test_display_hex_conflict_never_merges_by_name(stack):
    draft(stack)
    with stack.sessions() as db:
        db.add(
            Product(
                product_id=bytes32_to_hex(KEY),
                name="Another",
                manufacturer_address=OWNER,
                registered_at=datetime(2026, 1, 1),
                block_number=0,
                tx_hash="0x",
            )
        )
        db.commit()
    with pytest.raises(ReconciliationRequired, match="Conflicting product"):
        stack.new().poll_once()
    assert counts(stack) == (2, 0, 0, 0)


def test_distinct_logs_in_one_transaction(stack):
    first, second = log("CheckpointRecorded", 2), log(
        "CheckpointRecorded", 2, 1, status=1
    )
    second["transactionHash"] = first["transactionHash"]
    stack.chain.events += [first, second]
    stack.new().poll_once()
    assert counts(stack) == (1, 2, 0, 3)


def test_existing_tagged_history_adopted_without_duplicates(stack):
    draft(stack)
    stack.chain.events.append(log("CheckpointRecorded", 2))
    worker = stack.new()
    worker.poll_once()
    with stack.sessions() as db:
        for model in (ChainEvent, ChainBlock, IndexerCursor, IndexedProduct):
            db.query(model).delete()
        db.commit()
    worker.poll_once()
    assert counts(stack) == (1, 1, 0, 2)


def test_fetch_merges_logs_and_reads_historical_metadata(stack):
    worker = stack.new()
    worker.product_registry = MagicMock()
    worker.shipment_tracker = MagicMock()
    for contract in (worker.product_registry, worker.shipment_tracker):
        for kind in (
            "ProductRegistered",
            "ProductMetadataUpdated",
            "CheckpointRecorded",
            "CustodyTransferred",
            "DeliveryCompleted",
        ):
            getattr(contract.events, kind).return_value.get_logs.return_value = []
    worker.product_registry.events.ProductRegistered.return_value.get_logs.return_value = [
        log("ProductRegistered", 1)
    ]
    worker.product_registry.events.ProductMetadataUpdated.return_value.get_logs.return_value = [
        log("ProductMetadataUpdated", 4)
    ]
    worker.shipment_tracker.events.CheckpointRecorded.return_value.get_logs.return_value = [
        log("CheckpointRecorded", 2)
    ]
    worker.product_registry.functions.getProduct.return_value.call.return_value = [
        KEY,
        OWNER,
        "Widget",
        "Historic",
        "ipfs://historic",
        1000,
    ]
    rows = EventIndexer._fetch_events(worker, 1, 5)
    assert [row["blockNumber"] for row in rows] == [1, 2, 4]
    assert rows[0]["registration_details"]["description"] == "Historic"
    worker.product_registry.functions.getProduct.return_value.call.assert_called_once_with(
        block_identifier=1
    )


def test_postgres_transaction_lock_serializes_indexers(stack):
    if stack.engine.dialect.name != "postgresql":
        pytest.skip("Postgres advisory lock regression")
    first, second = stack.new(), stack.new()
    with stack.sessions() as db:
        first._lock(db)
        with pytest.raises(IndexerBusy):
            second.poll_once()
        assert counts(stack) == (0, 0, 0, 0)
        db.rollback()
    second.poll_once()
    first.poll_once()
    assert counts(stack) == (1, 0, 0, 1)


def test_postgres_process_loss_releases_writer_lock(stack):
    if stack.engine.dialect.name != "postgresql":
        pytest.skip("Postgres process-loss regression")
    import subprocess
    import sys

    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            """
import os,sys
from sqlalchemy import create_engine,text
engine=create_engine(os.environ['INDEXER_TEST_DATABASE_URL'])
with engine.connect() as conn:
    conn.execute(text('SELECT pg_advisory_xact_lock(864382025)'))
    print('locked',flush=True)
    sys.stdin.readline()
""",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(IndexerBusy):
            stack.new().poll_once()
    finally:
        child.terminate()
        child.wait(timeout=5)
    stack.new().poll_once()
    assert counts(stack) == (1, 0, 0, 1)


@pytest.mark.parametrize("kind", ["DeliveryCompleted", "CheckpointRecorded"])
def test_incomplete_delivery_pair_cannot_advance_cursor(stack, kind):
    stack.chain.events.append(log(kind, 2, status=3))
    with pytest.raises(RuntimeError, match="delivery event pair"):
        stack.new().poll_once()
    assert counts(stack) == (0, 0, 0, 0)


def test_reorg_beyond_window_requires_operator_review(stack, monkeypatch):
    worker = stack.new()
    worker.poll_once()
    fork(stack, 1)
    monkeypatch.setattr(settings, "indexer_max_reorg_depth", 1)
    with pytest.raises(ReconciliationRequired, match="ancestor"):
        worker.poll_once()
    assert counts(stack) == (1, 0, 0, 1)


def test_unknown_tagged_legacy_history_is_not_silently_retained(stack):
    draft(stack)
    with stack.sessions() as db:
        db.add(
            Checkpoint(
                product_id="PROD-TEST",
                location="Phantom",
                status="0",
                handler_address=OWNER,
                timestamp=datetime(2026, 1, 1),
                block_number=2,
                tx_hash="0x" + "aa" * 32,
                source_event_id=f"{settings.chain_id}:{TRACKER}:0x"
                + ("aa" * 32)
                + ":9",
            )
        )
        db.commit()
    with pytest.raises(ReconciliationRequired, match="not covered"):
        stack.new().poll_once()
    assert counts(stack) == (1, 1, 0, 0)


@pytest.mark.parametrize("mismatch", [False, True])
def test_archiveless_rpc_uses_only_matching_canonical_registration_calldata(
    stack, mismatch
):
    worker = stack.new()
    contract = MagicMock()
    contract.functions.getProduct.return_value.call.side_effect = RuntimeError(
        "historical state unavailable"
    )
    event = log("ProductRegistered", 1)
    worker.w3.eth.get_transaction = lambda _: dict(
        to=REGISTRY,
        **{"from": OWNER},
        blockNumber=1,
        blockHash=h(99 if mismatch else 1),
        input="encoded",
    )
    contract.decode_function_input.return_value = (
        SimpleNamespace(fn_name="registerProduct"),
        dict(
            productId=KEY,
            name="Widget",
            description="From calldata",
            metadataURI="ipfs://original",
        ),
    )
    if mismatch:
        with pytest.raises(ReconciliationRequired, match="transaction does not match"):
            worker._registration_details(contract, event)
    else:
        assert (
            worker._registration_details(contract, event)["description"]
            == "From calldata"
        )
