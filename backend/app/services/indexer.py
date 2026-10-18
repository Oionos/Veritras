"""Single-writer, transactional chain journal and reversible projections.

RPC responses are collected before projection writes. Every batch, including a
rewind, commits its journal, projections, block anchors and cursor together.
"""

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy import text, or_, func
from web3 import Web3

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.chain import ChainBlock, ChainEvent, IndexedProduct, IndexerCursor
from app.models.product import Product
from app.models.shipment import Checkpoint, CustodyTransfer, Shipment

logger = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
# A transaction-level lock works through transaction pooling and is released on
# commit, rollback, connection loss or process termination. All scopes share it:
# the existing business tables are a single projection, not independent tenants.
WRITER_LOCK = 864382025


class IndexerBusy(RuntimeError):
    pass


class ReconciliationRequired(RuntimeError):
    pass


def bytes32_to_hex(value) -> str:
    return Web3.to_hex(value)


def timestamp_to_datetime(ts) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def load_abi(contract_name: str) -> list:
    with open(
        BACKEND_DIR / "app" / "abi" / f"{contract_name}.json", encoding="utf-8-sig"
    ) as stream:
        return json.load(stream)


def find_product(db, value):
    hex_id = bytes32_to_hex(value)
    candidates = [hex_id]
    try:
        display_id = bytes(value).rstrip(b"\x00").decode("utf-8")
        if display_id:
            candidates.append(display_id)
    except UnicodeDecodeError:
        pass
    matches = (
        db.query(Product)
        .filter(
            or_(
                Product.product_id.in_(candidates),
                func.lower(Product.product_id) == hex_id,
            )
        )
        .with_for_update()
        .all()
    )
    if len(matches) > 1:
        raise ReconciliationRequired(
            "Conflicting product identities require reconciliation"
        )
    return matches[0] if matches else None


def _hex(value):
    result = Web3.to_hex(value).lower()
    if len(result) != 66:
        raise ValueError("Expected a 32-byte chain identity")
    return result


def _json_value(value):
    if isinstance(value, bytes):
        return Web3.to_hex(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


PRODUCT_FIELDS = (
    "name",
    "description",
    "metadata_uri",
    "manufacturer_address",
    "owner_address",
    "ownership_source",
    "registered_at",
    "block_number",
    "tx_hash",
)


class EventIndexer:
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        product_registry_address: Optional[str] = None,
        shipment_tracker_address: Optional[str] = None,
        poll_interval: Optional[int] = None,
    ):
        self.rpc_url = rpc_url or settings.sepolia_rpc_url
        self.product_registry_address = (
            product_registry_address or settings.product_registry_contract
        )
        self.shipment_tracker_address = (
            shipment_tracker_address or settings.shipment_tracker_contract
        )
        self.poll_interval = poll_interval or settings.indexer_poll_interval
        self.w3 = self.product_registry = self.shipment_tracker = None
        self.running = False
        self._thread = None
        self._stop_event = threading.Event()
        self.last_error = self.last_success_at = self._last_success_monotonic = None
        self.last_processed_block = self.chain_head = self.target_head = None
        self.last_reorg_ancestor = None
        self.recovery_reason = None
        self._batch_size = settings.indexer_batch_size

    @property
    def scope(self):
        value = f"{settings.chain_id}:{self.product_registry_address.lower()}:{self.shipment_tracker_address.lower()}"
        return hashlib.sha256(value.encode()).hexdigest()

    def _connect(self):
        if (
            not self.rpc_url
            or not Web3.is_address(self.product_registry_address)
            or not Web3.is_address(self.shipment_tracker_address)
        ):
            raise ValueError("RPC and valid contract addresses are required")
        self.w3 = Web3(
            Web3.HTTPProvider(
                self.rpc_url, request_kwargs={"timeout": settings.indexer_rpc_timeout}
            )
        )
        if not self.w3.is_connected() or self.w3.eth.chain_id != settings.chain_id:
            raise ConnectionError("RPC chain is unavailable or mismatched")
        self.product_registry = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.product_registry_address),
            abi=load_abi("ProductRegistry"),
        )
        self.shipment_tracker = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.shipment_tracker_address),
            abi=load_abi("ShipmentTracker"),
        )
        if (
            self.shipment_tracker.functions.productRegistry().call().lower()
            != self.product_registry_address.lower()
        ):
            raise ValueError("Tracker is not linked to the configured registry")

    def start(self):
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=settings.indexer_rpc_timeout + 2)

    def health(self) -> Dict:
        age = (
            None
            if self._last_success_monotonic is None
            else time.monotonic() - self._last_success_monotonic
        )
        lag = (
            None
            if self.target_head is None or self.last_processed_block is None
            else max(0, self.target_head - self.last_processed_block)
        )
        if not self.running or (
            self._thread is not None and not self._thread.is_alive()
        ):
            status = "stopped"
        elif self.last_error or (
            age is not None
            and age > max(settings.indexer_stale_after, self.poll_interval * 3)
        ):
            status = "degraded"
        elif age is None:
            status = "starting"
        else:
            status = "catching_up" if lag else "current"
        return dict(
            status=status,
            last_processed_block=self.last_processed_block,
            chain_head=self.chain_head,
            target_head=self.target_head,
            lag_blocks=lag,
            last_success_at=self.last_success_at,
            last_error=self.last_error,
            poll_interval_seconds=self.poll_interval,
            chain_id=settings.chain_id,
            confirmation_policy="depth",
            confirmations=settings.indexer_confirmations,
            cursor_storage="database",
            last_reorg_ancestor=self.last_reorg_ancestor,
            recovery_reason=self.recovery_reason,
        )

    def _run(self):
        while not self._stop_event.is_set():
            try:
                if self.product_registry is None:
                    self._connect()
                changed = self.poll_once()
                self.last_success_at = datetime.now(timezone.utc).isoformat()
                self._last_success_monotonic = time.monotonic()
                self.last_error = None
                self.recovery_reason = None
                if changed:
                    from app.services.events import broadcaster

                    broadcaster.publish_from_thread("chain_updated", changed)
                if self.last_processed_block >= self.target_head:
                    self._stop_event.wait(self.poll_interval)
            except Exception as error:
                # Never emit provider exceptions: they can contain credentialed URLs.
                self.last_error = type(error).__name__
                self.recovery_reason = (
                    str(error)
                    if isinstance(error, (IndexerBusy, ReconciliationRequired))
                    else None
                )
                logger.error("Indexer startup/poll failed: %s", self.last_error)
                if not isinstance(error, (IndexerBusy, ReconciliationRequired)):
                    self.product_registry = self.shipment_tracker = None
                self._stop_event.wait(settings.indexer_retry_interval)
        self.running = False

    def _lock(self, db):
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            if not db.execute(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": WRITER_LOCK}
            ).scalar():
                raise IndexerBusy("Another indexer owns the projection transaction")
        elif dialect == "sqlite":
            # Local-only fallback. Serializes separate SQLite writers too.
            db.execute(text("BEGIN IMMEDIATE"))
        else:
            raise RuntimeError("Unsupported indexer database")

    def _header(self, number):
        block = self.w3.eth.get_block(number)
        if block["number"] != number:
            raise ValueError("RPC block number mismatch")
        return _hex(block["hash"])

    def poll_once(self):
        """One atomic batch. Exposed for deterministic integration/recovery checks."""
        self.chain_head = self.w3.eth.block_number
        self.target_head = max(0, self.chain_head - settings.indexer_confirmations)
        changed = None
        with SessionLocal() as db:
            try:
                self._lock(db)
                cursor = db.get(IndexerCursor, self.scope)
                if cursor is None:
                    if settings.indexer_start_block > self.target_head:
                        raise ReconciliationRequired(
                            "Deployment anchor is ahead of confirmed chain"
                        )
                    cursor = IndexerCursor(
                        scope=self.scope,
                        chain_id=settings.chain_id,
                        registry_address=self.product_registry_address.lower(),
                        tracker_address=self.shipment_tracker_address.lower(),
                        start_block=settings.indexer_start_block,
                        last_processed_block=settings.indexer_start_block,
                        block_hash=self._header(settings.indexer_start_block),
                        updated_at=datetime.now(timezone.utc),
                    )
                    db.add(cursor)
                    db.add(
                        ChainBlock(
                            scope=self.scope,
                            number=cursor.start_block,
                            block_hash=cursor.block_hash,
                        )
                    )
                    db.flush()
                if cursor.start_block != settings.indexer_start_block:
                    raise ReconciliationRequired(
                        "Deployment anchor changed; explicit reconciliation required"
                    )
                # A lower/stale RPC head never silently deletes committed history.
                if self.chain_head < cursor.last_processed_block:
                    raise ReconciliationRequired(
                        "RPC head is behind the committed cursor"
                    )
                if self._header(cursor.last_processed_block) != cursor.block_hash:
                    ancestor = self._rewind(db, cursor)
                    changed = {"scope": self.scope, "reorg_ancestor": ancestor}
                start = cursor.last_processed_block + 1
                end = min(
                    self.target_head, cursor.last_processed_block + self._batch_size
                )
                if start <= end:
                    end_hash = self._header(end)
                    events = self._fetch_events(start, end)
                    self._validate_delivery_pairs(events)
                    headers = {end: end_hash}
                    for event in events:
                        number = event["blockNumber"]
                        if number not in headers:
                            headers[number] = self._header(number)
                        if _hex(event["blockHash"]) != headers[number]:
                            raise RuntimeError("Chain changed while fetching logs")
                        self._journal(db, event)
                    # Include projection flush errors in this transaction; cursor
                    # cannot advance when even the last event fails to persist.
                    db.flush()
                    if (
                        self._header(end) != end_hash
                        or self._header(cursor.last_processed_block)
                        != cursor.block_hash
                    ):
                        raise RuntimeError("Chain changed during projection")
                    for number, block_hash in headers.items():
                        anchor = db.get(ChainBlock, (self.scope, number))
                        if anchor is None:
                            db.add(
                                ChainBlock(
                                    scope=self.scope,
                                    number=number,
                                    block_hash=block_hash,
                                )
                            )
                        else:
                            anchor.block_hash = block_hash
                    if end == self.target_head:
                        self._validate_history_coverage(db)
                    cursor.last_processed_block, cursor.block_hash = end, end_hash
                    changed = dict(changed or {}, scope=self.scope, indexed_block=end)
                cursor.updated_at = datetime.now(timezone.utc)
                processed = cursor.last_processed_block
                db.commit()
            except Exception:
                db.rollback()
                raise
        # Only published after a successful commit. Reconnecting clients refetch.
        self.last_processed_block = processed
        if changed and "reorg_ancestor" in changed:
            self.last_reorg_ancestor = changed["reorg_ancestor"]
        self._batch_size = min(settings.indexer_batch_size, self._batch_size * 2)
        return changed

    def _fetch_events(self, start, end):
        result = []
        sources = (
            (self.product_registry, ("ProductRegistered", "ProductMetadataUpdated")),
            (
                self.shipment_tracker,
                ("CheckpointRecorded", "CustodyTransferred", "DeliveryCompleted"),
            ),
        )
        try:
            for contract, names in sources:
                for name in names:
                    for log in getattr(contract.events, name)().get_logs(
                        from_block=start, to_block=end
                    ):
                        item = dict(log)
                        item["event"] = name
                        if not start <= item["blockNumber"] <= end:
                            raise ValueError("Log outside requested range")
                        # Registration events omit description/initial URI. Read
                        # historical state at this block, never latest state.
                        if name == "ProductRegistered":
                            item["registration_details"] = self._registration_details(
                                contract, item
                            )
                        result.append(item)
        except Exception:
            self._batch_size = max(1, self._batch_size // 2)
            raise
        return sorted(
            result,
            key=lambda event: (
                event["blockNumber"],
                event["transactionIndex"],
                event["logIndex"],
            ),
        )

    def _registration_details(self, contract, event):
        args = event["args"]
        try:
            info = contract.functions.getProduct(args["productId"]).call(
                block_identifier=event["blockNumber"]
            )
        except Exception:
            # Some public RPCs retain transactions but not old account state.
            # Direct registerProduct calldata contains the immutable description
            # and initial URI. Validate its exact canonical inclusion and scope.
            tx = self.w3.eth.get_transaction(event["transactionHash"])
            if (
                (tx.get("to") or "").lower() != self.product_registry_address.lower()
                or tx["from"].lower() != args["manufacturer"].lower()
                or tx["blockNumber"] != event["blockNumber"]
                or _hex(tx["blockHash"]) != _hex(event["blockHash"])
            ):
                raise ReconciliationRequired(
                    "Historical registration transaction does not match log"
                )
            function, inputs = contract.decode_function_input(tx["input"])
            if (
                function.fn_name != "registerProduct"
                or bytes(inputs["productId"]) != bytes(args["productId"])
                or inputs["name"] != args["name"]
            ):
                raise ReconciliationRequired(
                    "Historical registration calldata does not match log"
                )
            return {
                "description": inputs["description"],
                "metadataURI": inputs["metadataURI"],
            }
        if (
            bytes(info[0]) != bytes(args["productId"])
            or info[1].lower() != args["manufacturer"].lower()
            or info[2] != args["name"]
            or info[5] != args["timestamp"]
        ):
            raise ReconciliationRequired(
                "Historical registration state does not match log"
            )
        return {"description": info[3], "metadataURI": info[4]}

    @staticmethod
    def _validate_delivery_pairs(events):
        # Both logs are emitted by one transaction in one block. A missing
        # counterpart indicates an incomplete RPC response; do not advance.
        delivered = {
            (event["transactionHash"], event["args"]["productId"])
            for event in events
            if event["event"] == "DeliveryCompleted"
        }
        checkpoints = {
            (event["transactionHash"], event["args"]["productId"])
            for event in events
            if event["event"] == "CheckpointRecorded" and event["args"]["status"] == 3
        }
        if delivered != checkpoints:
            raise RuntimeError("Incomplete delivery event pair")

    def _journal(self, db, event):
        name, address = event["event"], event["address"].lower()
        expected = (
            self.product_registry_address
            if name in ("ProductRegistered", "ProductMetadataUpdated")
            else self.shipment_tracker_address
        )
        if address != expected.lower() or event.get("removed", False):
            raise ValueError("Unexpected emitter or removed log")
        for key in ("logIndex", "transactionIndex", "blockNumber"):
            if type(event[key]) is not int or event[key] < 0:
                raise ValueError("Invalid event position")
        product_key = _hex(event["args"]["productId"])
        event_id = f"{settings.chain_id}:{address}:{_hex(event['transactionHash'])}:{event['logIndex']}"
        block_hash = _hex(event["blockHash"])
        occurrence = hashlib.sha256(f"{event_id}:{block_hash}".encode()).hexdigest()
        row = db.get(ChainEvent, occurrence)
        if row is not None and row.scope != self.scope:
            raise ReconciliationRequired(
                "Event belongs to another projection configuration"
            )
        if row is not None and row.canonical:
            return
        payload = _json_value(dict(event["args"]))
        if name == "ProductRegistered":
            payload["_registration"] = event["registration_details"]
        if row is None:
            row = ChainEvent(
                occurrence_id=occurrence,
                scope=self.scope,
                event_id=event_id,
                chain_id=settings.chain_id,
                contract_address=address,
                transaction_hash=_hex(event["transactionHash"]),
                log_index=event["logIndex"],
                transaction_index=event["transactionIndex"],
                block_number=event["blockNumber"],
                block_hash=block_hash,
                event_type=name,
                product_key=product_key,
                payload=payload,
                canonical=True,
                processed_at=datetime.now(timezone.utc),
            )
            db.add(row)
        else:
            row.canonical = True
            row.processed_at = datetime.now(timezone.utc)
        self._project(db, row)
        db.flush()

    def _binding(self, db, row):
        binding = db.get(IndexedProduct, (self.scope, row.product_key))
        if binding is not None:
            return (
                binding,
                db.query(Product)
                .filter_by(product_id=binding.product_id)
                .with_for_update()
                .one(),
            )
        if row.event_type != "ProductRegistered":
            raise ReconciliationRequired("Registration missing before product history")
        product = find_product(db, bytes.fromhex(row.product_key[2:]))
        if product is not None:
            if (
                db.query(IndexedProduct)
                .filter_by(product_id=product.product_id)
                .first()
            ):
                raise ReconciliationRequired(
                    "Product is bound to another chain configuration"
                )
            # Untagged history cannot be safely attributed to individual logs.
            for model in (Checkpoint, CustodyTransfer):
                if (
                    db.query(model)
                    .filter_by(product_id=product.product_id, source_event_id=None)
                    .first()
                ):
                    raise ReconciliationRequired(
                        "Legacy history needs explicit log reconciliation"
                    )
            if product.block_number > 0 and (
                product.block_number != row.block_number
                or product.tx_hash.lower() != row.transaction_hash
            ):
                raise ReconciliationRequired(
                    "Legacy registration conflicts with canonical log"
                )
            baseline = {field: getattr(product, field) for field in PRODUCT_FIELDS}
            baseline["registered_at"] = baseline["registered_at"].isoformat()
            if product.block_number > 0:
                # An old projection is not the pre-registration state. On orphan
                # recovery preserve its URL but revoke unsupported evidence/rights.
                baseline.update(
                    block_number=0,
                    tx_hash="0x",
                    owner_address=None,
                    ownership_source=None,
                    description=None,
                    metadata_uri=None,
                )
        else:
            baseline = dict(
                name=row.payload["name"],
                description=None,
                metadata_uri=None,
                manufacturer_address=row.payload["manufacturer"],
                owner_address=None,
                ownership_source=None,
                registered_at=timestamp_to_datetime(
                    row.payload["timestamp"]
                ).isoformat(),
                block_number=0,
                tx_hash="0x",
            )
            product = Product(
                product_id=row.product_key,
                **dict(
                    baseline,
                    registered_at=datetime.fromisoformat(baseline["registered_at"]),
                ),
            )
            db.add(product)
            db.flush()
        binding = IndexedProduct(
            scope=self.scope,
            product_key=row.product_key,
            product_id=product.product_id,
            baseline=baseline,
            status="0",
        )
        db.add(binding)
        db.flush()
        return binding, product

    def _project(self, db, row):
        args = row.payload
        binding, product = self._binding(db, row)
        if row.event_type == "ProductRegistered":
            product.name = args["name"]
            product.description = args["_registration"]["description"] or None
            product.metadata_uri = args["_registration"]["metadataURI"] or None
            product.manufacturer_address = args["manufacturer"]
            product.owner_address, product.ownership_source = (
                args["manufacturer"].lower(),
                "chain_event",
            )
            product.registered_at = timestamp_to_datetime(args["timestamp"])
            product.block_number, product.tx_hash = (
                row.block_number,
                row.transaction_hash,
            )
        elif row.event_type == "ProductMetadataUpdated":
            product.metadata_uri = args["metadataURI"] or None
        elif row.event_type in ("CheckpointRecorded", "CustodyTransferred"):
            if row.event_type == "CheckpointRecorded":
                model = Checkpoint
                values = dict(
                    location=args["location"],
                    status=str(args["status"]),
                    handler_address=args["handler"],
                    notes=args["notes"] or None,
                )
                binding.status, binding.current_handler = (
                    str(args["status"]),
                    args["handler"],
                )
            else:
                model = CustodyTransfer
                values = dict(from_address=args["from"], to_address=args["to"])
                binding.current_handler = args["to"]
            values.update(
                product_id=product.product_id,
                timestamp=timestamp_to_datetime(args["timestamp"]),
                block_number=row.block_number,
                tx_hash=row.transaction_hash,
                source_event_id=row.event_id,
            )
            existing = db.query(model).filter_by(source_event_id=row.event_id).first()
            if existing is None:
                db.add(model(**values))
            else:
                for key, value in values.items():
                    current = getattr(existing, key)
                    if isinstance(value, datetime):
                        current = (
                            current.replace(tzinfo=timezone.utc)
                            if current.tzinfo is None
                            else current
                        )
                    elif key.endswith("address") or key == "tx_hash":
                        current, value = current.lower(), value.lower()
                    if current != value:
                        raise ReconciliationRequired(
                            "Existing event projection conflicts with canonical log"
                        )
        elif row.event_type == "DeliveryCompleted":
            # The contract emits this BEFORE its Delivered checkpoint. It sets
            # state but never invents a checkpoint, location or notes.
            binding.status, binding.current_handler = "3", args["handler"]
        else:
            raise ValueError("Unsupported journal event")
        db.flush()
        for shipment in (
            db.query(Shipment).filter_by(product_id=product.product_id).all()
        ):
            shipment.status = binding.status

    def _validate_history_coverage(self, db):
        # Existing tagged rows are adopted only if their authoritative logs were
        # actually found. Never silently retain a phantom/stale projection.
        products = db.query(IndexedProduct.product_id).filter_by(scope=self.scope)
        identities = db.query(ChainEvent.event_id).filter_by(
            scope=self.scope, canonical=True
        )
        for model in (Checkpoint, CustodyTransfer):
            invalid = (
                db.query(model.id)
                .filter(
                    model.product_id.in_(products),
                    or_(
                        model.source_event_id.is_(None),
                        ~model.source_event_id.in_(identities),
                    ),
                )
                .first()
            )
            if invalid:
                raise ReconciliationRequired(
                    "History is not covered by canonical journal; explicit review required"
                )

    def _rewind(self, db, cursor):
        anchors = (
            db.query(ChainBlock)
            .filter(
                ChainBlock.scope == self.scope,
                ChainBlock.number <= cursor.last_processed_block,
                ChainBlock.number
                >= max(
                    cursor.start_block,
                    cursor.last_processed_block - settings.indexer_max_reorg_depth,
                ),
            )
            .order_by(ChainBlock.number.desc())
            .all()
        )
        ancestor = next(
            (
                anchor
                for anchor in anchors
                if self._header(anchor.number) == anchor.block_hash
            ),
            None,
        )
        if ancestor is None:
            raise ReconciliationRequired(
                "No canonical ancestor in recovery window; operator reconciliation required"
            )
        orphaned = (
            db.query(ChainEvent)
            .filter(
                ChainEvent.scope == self.scope,
                ChainEvent.canonical.is_(True),
                ChainEvent.block_number > ancestor.number,
            )
            .all()
        )
        affected = {row.product_key for row in orphaned}
        for row in orphaned:
            row.canonical = False
        db.flush()
        for key in affected:
            binding = db.get(IndexedProduct, (self.scope, key))
            product = (
                db.query(Product)
                .filter_by(product_id=binding.product_id)
                .with_for_update()
                .one()
            )
            for field, value in binding.baseline.items():
                setattr(
                    product,
                    field,
                    (
                        datetime.fromisoformat(value)
                        if field == "registered_at"
                        else value
                    ),
                )
            binding.status, binding.current_handler = "0", None
            # Only delete rows attributed to this product's journal, preserving
            # unrelated drafts, planning fields and unowned legacy records.
            identities = db.query(ChainEvent.event_id).filter_by(
                scope=self.scope, product_key=key
            )
            for model in (Checkpoint, CustodyTransfer):
                db.query(model).filter(model.source_event_id.in_(identities)).delete(
                    synchronize_session=False
                )
            for shipment in (
                db.query(Shipment).filter_by(product_id=product.product_id).all()
            ):
                shipment.status = "0"
            db.flush()
            canonical = (
                db.query(ChainEvent)
                .filter_by(scope=self.scope, product_key=key, canonical=True)
                .order_by(
                    ChainEvent.block_number,
                    ChainEvent.transaction_index,
                    ChainEvent.log_index,
                )
                .all()
            )
            for row in canonical:
                self._project(db, row)
        db.query(ChainBlock).filter(
            ChainBlock.scope == self.scope, ChainBlock.number > ancestor.number
        ).delete(synchronize_session=False)
        cursor.last_processed_block, cursor.block_hash = (
            ancestor.number,
            ancestor.block_hash,
        )
        return ancestor.number
