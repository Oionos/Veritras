"""Legacy attribution never guesses a log index or removes duplicate rows."""

from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.models.product import Product
from app.models.shipment import Checkpoint
from app.services.indexer import ReconciliationRequired
from manage_indexer import reconcile

ADDRESS = "0x" + "1" * 40
KEY = b"LEGACY".ljust(32, b"\x00")
TX = b"\xaa" * 32


@pytest.fixture
def legacy():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        db.add(
            Product(
                product_id="LEGACY",
                name="Existing",
                manufacturer_address=ADDRESS,
                registered_at=datetime(2026, 1, 1),
                block_number=0,
                tx_hash="0x",
            )
        )
        db.flush()
        row = Checkpoint(
            product_id="LEGACY",
            location="Factory",
            status="0",
            handler_address=ADDRESS,
            timestamp=datetime.fromtimestamp(1000, tz=timezone.utc),
            block_number=10,
            tx_hash="0x" + TX.hex(),
        )
        db.add(row)
        db.commit()
        event = dict(
            event="CheckpointRecorded",
            address=ADDRESS,
            transactionHash=TX,
            blockNumber=10,
            logIndex=7,
            args=dict(
                productId=KEY,
                location="Factory",
                status=0,
                handler=ADDRESS,
                timestamp=1000,
                notes="",
            ),
        )
        yield db, row, event
    engine.dispose()


def test_dry_run_and_exact_attribution_are_repeatable(legacy):
    db, row, event = legacy
    assert reconcile(None, db, [event])["matched_rows"] == 1
    assert row.source_event_id is None
    assert reconcile(None, db, [event], apply=True)["applied"]
    db.commit()
    assert row.source_event_id.endswith(":7")
    assert reconcile(None, db, [event])["matched_rows"] == 0


def test_two_logs_same_transaction_require_payload_match(legacy):
    db, row, event = legacy
    import copy

    second = copy.deepcopy(event)
    second["logIndex"] = 8
    assert reconcile(None, db, [event, second])["conflicts"]
    with pytest.raises(ReconciliationRequired):
        reconcile(None, db, [event, second], apply=True)
    assert row.source_event_id is None


def test_duplicate_legacy_rows_are_preserved_and_block_apply(legacy):
    db, row, event = legacy
    fields = {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name != "id"
    }
    db.add(Checkpoint(**fields))
    db.commit()
    with pytest.raises(ReconciliationRequired):
        reconcile(None, db, [event], apply=True)
    assert db.query(Checkpoint).count() == 2
    assert db.query(Checkpoint).filter_by(source_event_id=None).count() == 2


def test_mismatched_payload_is_not_attributed(legacy):
    db, row, event = legacy
    event["args"]["notes"] = "Different event"
    assert reconcile(None, db, [event])["conflicts"]
    assert row.source_event_id is None
