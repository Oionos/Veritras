"""Controlled clocks, canonical recovery and off-chain permission boundaries."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from sqlalchemy import event as sql_event
from app.core.auth import create_access_token
from app.models.chain import ChainBlock, ChainEvent, IndexedProduct, IndexerCursor
from app.models.exception import ShipmentException, ExceptionEvaluation
from app.models.product import Product
from app.models.shipment import Shipment
from app.schemas.exception import PolicyResponse
from app.services.analytics import shipment_dataset, utc
from app.services.exceptions import conditions, evaluate, current_scope, ExceptionWorker

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
OWNER = "0x1234567890123456789012345678901234567890"
HANDLER = "0x" + "5" * 40
HEALTH = dict(
    enabled=True,
    ready=True,
    status="current",
    last_processed_block=100,
    lag_blocks=0,
    finality_gap_blocks=0,
)


def seed(db):
    from app.services.identity import scope_values

    p = Product(
        product_id="PROD-EXCEPTION",
        name="Coffee",
        manufacturer_address=OWNER,
        owner_address=OWNER,
        ownership_source="chain_event",
        registration_status="indexed",
        registered_at=START,
        block_number=1,
        tx_hash="0x01",
        **scope_values("PROD-EXCEPTION"),
    )
    db.add(p)
    db.flush()
    s = Shipment(
        shipment_id="SHIP-EXCEPTION",
        product_id=p.product_id,
        origin="Manila",
        destination="Cebu",
        expected_arrival_at=START + timedelta(hours=8),
        expected_arrival_recorded_at=START - timedelta(hours=1),
    )
    db.add_all(
        [
            s,
            IndexedProduct(
                scope=current_scope(),
                product_key=p.on_chain_product_id,
                product_id=p.product_id,
                baseline={},
                status="1",
            ),
            IndexerCursor(
                scope=current_scope(),
                chain_id=p.chain_id,
                registry_address=p.registry_address,
                tracker_address=p.tracker_address,
                start_block=0,
                last_processed_block=100,
                block_hash="0xabc",
                updated_at=START,
            ),
            ChainBlock(scope=current_scope(), number=100, block_hash="0xabc"),
        ]
    )
    db.flush()
    add_event(db, 1, "ProductRegistered", registry=True)
    add_event(db, 2, "CheckpointRecorded", status=1, handler=OWNER, location="Manila")
    db.commit()
    return s


def add_event(db, n, kind, *, at=START, registry=False, **payload):
    p = db.query(Product).filter_by(product_id="PROD-EXCEPTION").one()
    e = ChainEvent(
        occurrence_id=str(n),
        event_id=str(n),
        scope=current_scope(),
        chain_id=p.chain_id,
        product_key=p.on_chain_product_id,
        contract_address=p.registry_address if registry else p.tracker_address,
        transaction_hash="0x" + f"{n:064x}",
        block_hash="0x" + f"{n:064x}",
        block_number=n,
        transaction_index=0,
        log_index=0,
        event_type=kind,
        canonical=True,
        processed_at=START,
        payload={"timestamp": int(at.timestamp()), **payload},
    )
    db.add(e)
    return e


def run(db, hours=25, health=None):
    db.commit()  # Production evaluator always starts with a fresh transaction.
    return evaluate(
        db,
        lambda: deepcopy(HEALTH if health is None else health),
        now=START + timedelta(hours=hours),
    )


def open_rows(db):
    return (
        db.query(ShipmentException)
        .filter_by(resolved_at=None)
        .order_by(ShipmentException.kind)
        .all()
    )


@pytest.fixture
def shipment(db_session):
    seed(db_session)
    return db_session


def test_threshold_boundaries_repeat_evaluation_and_restart(shipment):
    db = shipment
    assert run(db, 7.999) is None
    assert open_rows(db) == []
    assert run(db, 8) is None
    first = open_rows(db)[0]
    assert first.kind == "arrival_overdue"
    arrival_id = first.id
    run(db, 24)
    assert {e.kind for e in open_rows(db)} == {
        "arrival_overdue",
        "checkpoint_inactivity",
    }
    run(db, 25)
    db.expire_all()
    assert db.query(ShipmentException).count() == 2
    first = db.get(ShipmentException, arrival_id)
    assert utc(first.triggered_at) == START + timedelta(hours=8)
    assert utc(first.first_observed_at) == START + timedelta(hours=8)
    assert utc(first.last_observed_at) == START + timedelta(hours=25)


@pytest.mark.parametrize(
    "health",
    [
        dict(HEALTH, enabled=False),
        dict(HEALTH, status="catching_up"),
        dict(HEALTH, ready=False),
        dict(HEALTH, lag_blocks=1),
        dict(HEALTH, finality_gap_blocks=1),
        dict(HEALTH, last_processed_block=None),
    ],
)
def test_paused_indexer_neither_opens_nor_resolves(shipment, health):
    db = shipment
    assert run(db, 25, health)
    assert db.query(ShipmentException).count() == 0
    run(db)
    add_event(db, 3, "DeliveryCompleted", at=START + timedelta(hours=26))
    assert run(db, 27, health)
    assert len(open_rows(db)) == 2
    assert run(db, 27) is None
    assert open_rows(db) == []


def test_custody_followup_uses_source_order_and_receiving_handler(shipment):
    db = shipment
    add_event(db, 3, "CustodyTransferred", **{"from": OWNER, "to": HANDLER})
    run(db, 6)
    row = open_rows(db)[0]
    assert row.kind == "custody_followup"
    occurrence = row.id
    add_event(db, 4, "CheckpointRecorded", status=2, handler=OWNER, location="Hub")
    run(db, 6)
    assert db.get(ShipmentException, occurrence).resolved_at is None
    add_event(db, 5, "CheckpointRecorded", status=2, handler=HANDLER, location="Hub")
    run(db, 6)
    assert db.get(ShipmentException, occurrence).resolved_at is not None
    run(db, 25)
    assert {e.kind for e in open_rows(db)} == {"arrival_overdue", "checkpoint_wait"}


def test_reorg_resolves_and_reopens_new_unacknowledged_episode(shipment):
    db = shipment
    run(db)
    old = open_rows(db)[0]
    old.acknowledged_at = START + timedelta(hours=25)
    old.acknowledged_by = OWNER
    add_event(db, 3, "DeliveryCompleted", at=START + timedelta(hours=26))
    run(db, 27)
    assert not open_rows(db)
    db.get(ChainEvent, "3").canonical = False
    run(db, 28)
    reopened = open_rows(db)
    assert len(reopened) == 2
    assert all(e.id != old.id and e.acknowledged_at is None for e in reopened)
    assert db.get(ShipmentException, old.id).acknowledged_by == OWNER


@pytest.mark.parametrize(
    "change",
    [
        {"scope": "other"},
        {"canonical": False},
        {"chain_id": 1},
        {"contract_address": "0x" + "9" * 40},
        {"product_key": "0x" + "f" * 64},
    ],
)
def test_wrong_identity_or_orphan_cannot_clear_exceptions(shipment, change):
    db = shipment
    run(db)
    e = add_event(db, 3, "DeliveryCompleted", at=START + timedelta(hours=26))
    for key, value in change.items():
        setattr(e, key, value)
    run(db, 27)
    assert len(open_rows(db)) == 2


@pytest.mark.parametrize(
    "timestamp",
    [
        None,
        "invalid",
        999999999999999999999999,
        int((START + timedelta(days=100)).timestamp()),
    ],
)
def test_uncertain_timestamps_preserve_prior_observations(shipment, timestamp):
    db = shipment
    run(db)
    add_event(
        db, 3, "CheckpointRecorded", timestamp=timestamp, status=2, handler=HANDLER
    )
    run(db, 26)
    assert len(open_rows(db)) == 2
    assert all(
        utc(e.last_observed_at) == START + timedelta(hours=25) for e in open_rows(db)
    )


def test_no_arrival_exception_for_plan_recorded_after_departure(shipment):
    db = shipment
    db.query(Shipment).one().expected_arrival_recorded_at = START + timedelta(seconds=1)
    run(db)
    assert [e.kind for e in open_rows(db)] == ["checkpoint_inactivity"]


def test_atomic_failure_rolls_back_episodes_and_evaluation(shipment):
    db = shipment

    def fail(*args):
        raise RuntimeError("interrupted write")

    sql_event.listen(db, "before_commit", fail)
    with pytest.raises(RuntimeError):
        evaluate(db, lambda: HEALTH, now=START + timedelta(hours=25))
    sql_event.remove(db, "before_commit", fail)
    db.rollback()
    assert db.query(ShipmentException).count() == 0
    assert db.query(ExceptionEvaluation).count() == 0
    run(db)
    assert len(open_rows(db)) == 2


def test_health_change_mid_evaluation_rolls_back(shipment):
    db = shipment
    db.commit()
    values = iter([HEALTH, dict(HEALTH, status="degraded")])
    assert (
        evaluate(db, lambda: next(values), now=START + timedelta(hours=25))
        == "indexer_changed"
    )
    assert not open_rows(db)


def test_cursor_anchor_and_clock_guards(shipment):
    db = shipment
    run(db)
    assert run(db, 24) == "clock_regressed"
    db.get(ChainBlock, (current_scope(), 100)).block_hash = "changed"
    assert run(db, 26) == "cursor_unavailable"
    assert len(open_rows(db)) == 2
    db.get(IndexerCursor, current_scope()).last_processed_block = 101
    assert run(db, 26) == "cursor_changed"


def test_owner_policy_revision_validation_and_episode_replacement(
    client_fixture, db_session
):
    seed(db_session)
    db = db_session
    run(db)
    old = [e.id for e in open_rows(db)]
    path = "/exceptions/policies/SHIP-EXCEPTION"
    assert client_fixture.get(path).json()["revision"] == 0
    body = dict(
        expected_revision=0,
        arrival_enabled=True,
        inactivity_hours=30,
        checkpoint_hours=None,
        custody_hours=6,
    )
    response = client_fixture.put(path, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 1
    assert client_fixture.put(path, json=body).status_code == 409
    body["expected_revision"] = 1
    assert client_fixture.put(path, json=body).json()["revision"] == 1
    run(db, 26)
    assert len(open_rows(db)) == 1
    assert (
        open_rows(db)[0].id in old
    )  # An unrelated rule change preserves its acknowledgement.
    assert sum(bool(db.get(ShipmentException, id).resolved_at) for id in old) == 1
    for invalid in [-1, 0, 0.1, 8761]:
        assert (
            client_fixture.put(path, json=dict(body, custody_hours=invalid)).status_code
            == 422
        )
    assert client_fixture.put(path, json=dict(body, unexpected="x")).status_code == 422


def test_ack_permissions_idempotency_and_resolved_conflict(client_fixture, db_session):
    seed(db_session)
    run(db_session)
    row = open_rows(db_session)[0]
    path = f"/exceptions/{row.id}/acknowledgement"
    client_fixture.headers.pop("Authorization")
    assert client_fixture.post(path, json={}).status_code == 401
    client_fixture.headers["Authorization"] = "Bearer " + create_access_token(HANDLER)
    assert client_fixture.post(path, json={}).status_code == 403
    assert (
        client_fixture.put(
            "/exceptions/policies/SHIP-EXCEPTION", json={"expected_revision": 0}
        ).status_code
        == 403
    )
    client_fixture.headers["Authorization"] = "Bearer " + create_access_token(OWNER)
    first = client_fixture.post(path, json={"note": "Checked with carrier"})
    assert first.status_code == 200, first.text
    assert client_fixture.post(path, json={"note": "Overwrite"}).json() == first.json()
    assert client_fixture.post(path, json={"note": "x" * 501}).status_code == 422
    db_session.expire_all()
    row = db_session.get(ShipmentException, row.id)
    row.resolved_at = START + timedelta(hours=26)
    db_session.commit()
    assert client_fixture.post(path, json={}).status_code == 409
    assert (
        client_fixture.post("/exceptions/missing/acknowledgement", json={}).status_code
        == 404
    )


def test_get_is_read_only_filters_history_pagination_and_scope(
    client_fixture, db_session, monkeypatch
):
    from app.api.routes import exceptions

    seed(db_session)
    monkeypatch.setattr(exceptions, "health", lambda: dict(HEALTH, enabled=False))
    assert client_fixture.get("/exceptions").json()["evaluation"]["paused"]
    assert db_session.query(ExceptionEvaluation).count() == 0
    run(db_session)
    rows = open_rows(db_session)
    rows[0].acknowledged_at = START
    db_session.commit()
    assert client_fixture.get("/exceptions?state=acknowledged").json()["total"] == 1
    assert client_fixture.get("/exceptions?state=unacknowledged").json()["total"] == 1
    assert len(client_fixture.get("/exceptions?limit=1").json()["items"]) == 1
    assert client_fixture.get("/exceptions?skip=1&limit=1").json()["total"] == 2
    assert client_fixture.get("/exceptions?shipment_id=other").json()["total"] == 0
    assert client_fixture.get("/exceptions?state=bad").status_code == 422
    assert client_fixture.get("/exceptions?limit=101").status_code == 422
    add_event(db_session, 3, "DeliveryCompleted", at=START + timedelta(hours=26))
    run(db_session, 27)
    assert client_fixture.get("/exceptions?state=open").json()["total"] == 0
    assert client_fixture.get("/exceptions?state=resolved").json()["total"] == 2
    assert client_fixture.get("/exceptions/policies/missing").status_code == 404


def test_disabled_worker_never_opens_database():
    from unittest.mock import Mock

    sessions = Mock(side_effect=AssertionError("No DB while disabled"))
    worker = ExceptionWorker(
        lambda: dict(HEALTH, enabled=False), session_factory=sessions, interval=0.01
    )
    worker.start()
    worker.stop()
    sessions.assert_not_called()
    assert not worker.thread.is_alive()


def test_changed_threshold_replaces_only_affected_occurrence(shipment):
    from app.models.exception import ExceptionPolicy

    db = shipment
    run(db)
    old = {e.kind: e.id for e in open_rows(db)}
    for e in open_rows(db):
        e.acknowledged_at, e.acknowledged_by = START, OWNER
    db.add(
        ExceptionPolicy(
            shipment_id="SHIP-EXCEPTION",
            revision=1,
            arrival_enabled=True,
            inactivity_hours=12.0,
            checkpoint_hours=24.0,
            custody_hours=6.0,
            updated_at=START,
            updated_by=OWNER,
        )
    )
    run(db, 26)
    rows = {e.kind: e for e in open_rows(db)}
    assert rows["arrival_overdue"].id == old["arrival_overdue"]
    assert rows["arrival_overdue"].acknowledged_at
    assert rows["checkpoint_inactivity"].id != old["checkpoint_inactivity"]
    assert rows["checkpoint_inactivity"].acknowledged_at is None
    assert (
        db.get(ShipmentException, old["checkpoint_inactivity"]).resolution
        == "condition_replaced"
    )


def test_new_transfer_restarts_followup_clock(shipment):
    db = shipment
    add_event(db, 3, "CustodyTransferred", **{"from": OWNER, "to": HANDLER})
    run(db, 6)
    first = open_rows(db)[0].id
    add_event(
        db,
        4,
        "CustodyTransferred",
        at=START + timedelta(hours=7),
        **{"from": HANDLER, "to": OWNER},
    )
    run(db, 8)
    assert db.get(ShipmentException, first).resolved_at
    assert not any(e.kind == "custody_followup" for e in open_rows(db))
    run(db, 13)
    followup = next(e for e in open_rows(db) if e.kind == "custody_followup")
    assert followup.id != first and followup.evidence["receiving_handler"] == OWNER


def test_orphaned_anchor_is_retained_as_withdrawn_history(shipment):
    db = shipment
    run(db)
    db.get(ChainEvent, "2").canonical = False
    run(db, 26)
    assert not open_rows(db)
    assert all(
        e.resolution == "evidence_withdrawn" for e in db.query(ShipmentException).all()
    )
