"""Reproducible, clock-injected rules and atomic off-chain exception episodes.

No RPC, writes on GET, or notification delivery. All writers use the indexer's
transaction lock so reorgs and concurrent evaluators cannot mix observations.
"""

import hashlib
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.chain import IndexerCursor, ChainBlock
from app.models.exception import ExceptionPolicy, ShipmentException, ExceptionEvaluation
from app.schemas.exception import PolicyResponse
from app.services.analytics import shipment_dataset, utc
from app.services.identity import require_current_scope
from app.services.indexer import WRITER_LOCK, IndexerBusy
from fastapi import HTTPException

logger = logging.getLogger("veritras.exceptions")


def current_scope():
    value = f"{settings.chain_id}:{settings.product_registry_contract.lower()}:{settings.shipment_tracker_contract.lower()}"
    return hashlib.sha256(value.encode()).hexdigest()


def writer_lock(db):
    if db.get_bind().dialect.name == "postgresql":
        if not db.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": WRITER_LOCK}
        ).scalar():
            raise IndexerBusy("Projection writer is busy")
    else:
        db.execute(text("BEGIN IMMEDIATE"))


def pause_reason(health):
    if not health.get("enabled"):
        return "indexing_disabled"
    if not health.get("ready") or health.get("status") != "current":
        return "indexer_not_current"
    if health.get("lag_blocks") != 0 or health.get("finality_gap_blocks") != 0:
        return "indexer_not_current"
    if health.get("last_processed_block") is None:
        return "cursor_unavailable"
    return None


def policy_for(db, shipment_id):
    row = db.get(ExceptionPolicy, shipment_id)
    return PolicyResponse.model_validate(row) if row else PolicyResponse()


def event_time(event):
    try:
        return datetime.fromtimestamp(int(event.payload["timestamp"]), timezone.utc)
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return None


def conditions(record, policy, now):
    """None means uncertain evidence: retain existing observations for review."""
    shipment = record["shipment"]
    try:
        require_current_scope(shipment.product)
    except HTTPException:
        return {}
    events = record["events"]
    if not any(
        e.event_type == "ProductRegistered" and e.scope == current_scope()
        for e in events
    ):
        return {}
    timed = [
        e
        for e in events
        if e.event_type
        in {"CheckpointRecorded", "CustodyTransferred", "DeliveryCompleted"}
    ]
    if any(event_time(e) is None or event_time(e) > now for e in timed):
        return None
    if record["delivered_at"]:
        return {}
    result = {}

    def add(kind, anchor, due, threshold=None, **details):
        # Exact threshold is overdue; no alerts before it.
        if now < due:
            return
        evidence = dict(
            product_id=shipment.product_id,
            anchor_event_id=anchor.event_id,
            anchor_occurrence_id=anchor.occurrence_id,
            threshold_hours=threshold,
            policy_revision=policy.revision,
            **details,
        )
        identity = f"{kind}:{anchor.occurrence_id}:{threshold}:{due.isoformat()}"
        result[kind] = dict(
            fingerprint=hashlib.sha256(identity.encode()).hexdigest(),
            triggered_at=due,
            evidence=evidence,
        )

    departure = record["departed_at"]
    if (
        policy.arrival_enabled
        and departure
        and shipment.expected_arrival_at
        and shipment.expected_arrival_recorded_at
        and utc(shipment.expected_arrival_recorded_at) <= departure
    ):
        anchor = next(
            e
            for e in events
            if e.event_type == "CheckpointRecorded"
            and str(e.payload.get("status")) == "1"
        )
        add("arrival_overdue", anchor, utc(shipment.expected_arrival_at))
    checkpoints = [e for e in events if e.event_type == "CheckpointRecorded"]
    if checkpoints:
        latest = checkpoints[-1]
        at_checkpoint = str(latest.payload.get("status")) == "2"
        threshold = (
            policy.checkpoint_hours if at_checkpoint else policy.inactivity_hours
        )
        # Created-only checkpoints do not establish an active shipment journey.
        if threshold is not None and (departure or at_checkpoint):
            add(
                "checkpoint_wait" if at_checkpoint else "checkpoint_inactivity",
                latest,
                event_time(latest) + timedelta(hours=threshold),
                threshold,
                location=str(latest.payload.get("location", "")),
            )
    transfers = [
        i for i, e in enumerate(events) if e.event_type == "CustodyTransferred"
    ]
    if transfers and policy.custody_hours is not None:
        position = transfers[-1]
        transfer = events[position]
        recipient = str(transfer.payload.get("to", "")).lower()
        if not recipient or recipient == "0x" + "0" * 40:
            return None
        followed_up = any(
            e.event_type == "CheckpointRecorded"
            and str(e.payload.get("handler", "")).lower() == recipient
            for e in events[position + 1 :]
        )
        if not followed_up:
            add(
                "custody_followup",
                transfer,
                event_time(transfer) + timedelta(hours=policy.custody_hours),
                policy.custody_hours,
                receiving_handler=recipient,
            )
    return result


def evaluate(db, health_provider, *, now=None):
    """Commit the entire evaluation or nothing. Caller supplies a fresh session."""
    now = utc(now or datetime.now(timezone.utc))
    before = health_provider()
    reason = pause_reason(before)
    if reason:
        return reason
    try:
        writer_lock(db)
        scope = current_scope()
        cursor = db.get(IndexerCursor, scope)
        if not cursor or cursor.last_processed_block != before["last_processed_block"]:
            db.rollback()
            return "cursor_changed"
        anchor = db.get(ChainBlock, (scope, cursor.last_processed_block))
        if not anchor or anchor.block_hash != cursor.block_hash:
            db.rollback()
            return "cursor_unavailable"
        previous = db.get(ExceptionEvaluation, scope)
        if previous and utc(previous.evaluated_at) > now:
            db.rollback()
            return "clock_regressed"
        records = shipment_dataset(db)
        policies = {
            p.shipment_id: PolicyResponse.model_validate(p)
            for p in db.query(ExceptionPolicy).all()
        }
        open_rows = (
            db.query(ShipmentException).filter_by(scope=scope, resolved_at=None).all()
        )
        active = {(r.shipment_id, r.kind): r for r in open_rows}
        seen = set()
        uncertain = set()
        canonical_anchors = {}
        for record in records:
            shipment_id = record["shipment"].shipment_id
            canonical_anchors[shipment_id] = {e.occurrence_id for e in record["events"]}
            expected = conditions(
                record, policies.get(shipment_id, PolicyResponse()), now
            )
            if expected is None:
                uncertain.add(shipment_id)
                continue
            for kind, values in expected.items():
                key = (shipment_id, kind)
                seen.add(key)
                row = active.get(key)
                if row and row.fingerprint != values["fingerprint"]:
                    row.resolved_at, row.resolution = now, "condition_replaced"
                    db.flush()  # Release partial unique index before replacement.
                    row = None
                if row is None:
                    db.add(
                        ShipmentException(
                            id=str(uuid.uuid4()),
                            scope=scope,
                            shipment_id=shipment_id,
                            kind=kind,
                            first_observed_at=now,
                            last_observed_at=now,
                            **values,
                        )
                    )
                else:
                    row.last_observed_at = now
                    row.evidence = values["evidence"]
        for key, row in active.items():
            if key not in seen and row.shipment_id not in uncertain:
                row.resolved_at = now
                row.resolution = (
                    "evidence_withdrawn"
                    if row.evidence["anchor_occurrence_id"]
                    not in canonical_anchors.get(row.shipment_id, set())
                    else "condition_cleared"
                )
        after = health_provider()
        if (
            pause_reason(after)
            or after["last_processed_block"] != before["last_processed_block"]
        ):
            db.rollback()
            return "indexer_changed"
        if previous is None:
            previous = ExceptionEvaluation(scope=scope)
            db.add(previous)
        previous.evaluated_at, previous.block_number, previous.block_hash = (
            now,
            cursor.last_processed_block,
            cursor.block_hash,
        )
        previous.uncertain_shipments = len(uncertain)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise


class ExceptionWorker:
    def __init__(self, health_provider, session_factory=SessionLocal, interval=60):
        self.health_provider, self.session_factory, self.interval = (
            health_provider,
            session_factory,
            interval,
        )
        self.stopping = threading.Event()
        self.thread = threading.Thread(
            target=self.run, name="shipment-exceptions", daemon=True
        )

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.thread.join(timeout=5)

    def run(self):
        while not self.stopping.is_set():
            try:
                if not pause_reason(self.health_provider()):
                    with self.session_factory() as db:
                        evaluate(db, self.health_provider)
            except IndexerBusy:
                pass  # Next tick retries; canonical ingestion always has priority.
            except Exception as error:
                logger.error("Exception evaluation failed: %s", type(error).__name__)
            self.stopping.wait(self.interval)
