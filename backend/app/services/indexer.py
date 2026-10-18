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

from sqlalchemy import text, or_
from web3 import Web3

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.chain import ChainBlock, ChainEvent, IndexedProduct, IndexerCursor
from app.models.product import Product
from app.services.indexer_health import IndexerHealth, utc_now
from app.services.identity import find_canonical_product, assign_identity, scope_values
from app.models.shipment import Checkpoint, CustodyTransfer, Shipment

logger = logging.getLogger("veritras.indexer")
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
    # Compatibility wrapper for read-only tooling; the writer passes its own
    # configured scope explicitly below.
    try:
        return find_canonical_product(
            db,
            bytes32_to_hex(value),
            settings.chain_id,
            settings.product_registry_contract,
        )
    except ValueError as error:
        raise ReconciliationRequired(str(error)) from None


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
    "chain_registered_at",
    "registration_status",
    "block_number",
    "tx_hash",
)


class IndexerConfigurationError(ValueError):
    """Internal constant error codes; never a provider exception message."""


class IndexerStopping(RuntimeError):
    pass


class EventIndexer(IndexerHealth):
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
        self.poll_interval = (
            settings.indexer_poll_interval if poll_interval is None else poll_interval
        )
        if not 1 <= self.poll_interval <= 3600:
            raise ValueError("Poll interval must be between 1 and 3600 seconds")
        self.w3 = self.product_registry = self.shipment_tracker = None
        self.running = False
        self._thread = None
        self._stop_event = threading.Event()
        self._init_health()
        self._batch_size = settings.indexer_batch_size

    @property
    def scope(self):
        value = f"{settings.chain_id}:{self.product_registry_address.lower()}:{self.shipment_tracker_address.lower()}"
        return hashlib.sha256(value.encode()).hexdigest()

    def _check_stopping(self):
        if self._stop_event.is_set():
            raise IndexerStopping()

    def _connect(self):
        from urllib.parse import urlsplit

        self._check_stopping()
        if not self.rpc_url:
            raise IndexerConfigurationError("rpc_not_configured")
        try:
            parsed = urlsplit(self.rpc_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError()
        except ValueError:
            raise IndexerConfigurationError("invalid_rpc_url") from None
        if (
            not Web3.is_address(self.product_registry_address)
            or not Web3.is_address(self.shipment_tracker_address)
            or int(self.product_registry_address, 16) == 0
            or int(self.shipment_tracker_address, 16) == 0
        ):
            raise IndexerConfigurationError("invalid_contract_address")
        w3 = Web3(
            Web3.HTTPProvider(
                self.rpc_url,
                request_kwargs={"timeout": settings.indexer_rpc_timeout},
                exception_retry_configuration=None,
            )
        )
        if not w3.is_connected():
            raise ConnectionError("RPC is unavailable")
        self._check_stopping()
        if w3.eth.chain_id != settings.chain_id:
            raise IndexerConfigurationError("chain_mismatch")
        self._check_stopping()
        registry = Web3.to_checksum_address(self.product_registry_address)
        tracker = Web3.to_checksum_address(self.shipment_tracker_address)
        for address in (registry, tracker):
            if not w3.eth.get_code(address):
                raise IndexerConfigurationError("contract_not_deployed")
            self._check_stopping()
        product_registry = w3.eth.contract(
            address=registry, abi=load_abi("ProductRegistry")
        )
        shipment_tracker = w3.eth.contract(
            address=tracker, abi=load_abi("ShipmentTracker")
        )
        if (
            shipment_tracker.functions.productRegistry().call().lower()
            != registry.lower()
        ):
            raise IndexerConfigurationError("tracker_registry_mismatch")
        self._check_stopping()
        # Publish only a completely validated connection, never a partial setup.
        self.w3, self.product_registry, self.shipment_tracker = (
            w3,
            product_registry,
            shipment_tracker,
        )

    def start(self):
        with self._health_lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop_event.is_set():
                    raise RuntimeError("Previous indexer thread is still stopping")
                return
            self.running = True
            self._stop_event.clear()
            self._started_monotonic = time.monotonic()
            self.started_at = utc_now()
            self._last_success_monotonic = self._last_progress_monotonic = None
            self.last_error = self.initialization_error = self.recovery_reason = None
            self.consecutive_failures = 0
            self.phase = "initializing"
            self._thread = threading.Thread(
                target=self._run, name="chain-indexer", daemon=True
            )
            try:
                self._thread.start()
            except Exception:
                self.running = False
                raise

    def stop(self):
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=settings.indexer_rpc_timeout + 2)
            if self._thread.is_alive():
                logger.warning("Indexer shutdown is waiting for an in-flight operation")
                return False
        self.running = False
        return True

    def _run(self):
        try:
            while not self._stop_event.is_set():
                initializing = self.product_registry is None
                try:
                    with self._health_lock:
                        self.phase = "initializing" if initializing else "polling"
                    if initializing:
                        self._connect()
                        initializing = False
                        with self._health_lock:
                            self.initialization_error = None
                            self.phase = "polling"
                    self._check_stopping()
                    previous = self.last_processed_block
                    changed = self.poll_once()
                    self._record_success(previous)
                    self._log_health_transition()
                    if changed:
                        from app.services.events import broadcaster

                        try:
                            broadcaster.publish_from_thread("chain_updated", changed)
                        except Exception as error:
                            logger.warning(
                                "Indexer notification failed: %s", type(error).__name__
                            )
                    if self.last_processed_block >= self.target_head:
                        self._stop_event.wait(self.poll_interval)
                except IndexerStopping:
                    break
                except Exception as error:
                    with self._health_lock:
                        self.last_error = type(error).__name__
                        if initializing:
                            self.initialization_error = self.last_error
                        self.last_poll_at = utc_now()
                        self._last_poll_monotonic = time.monotonic()
                        self.recovery_reason = (
                            "writer_busy"
                            if isinstance(error, IndexerBusy)
                            else (
                                "reconciliation_required"
                                if isinstance(error, ReconciliationRequired)
                                else (
                                    "initialization_failed"
                                    if initializing
                                    else "poll_failed"
                                )
                            )
                        )
                        if isinstance(error, IndexerConfigurationError) and str(
                            error
                        ) in {
                            "rpc_not_configured",
                            "invalid_rpc_url",
                            "invalid_contract_address",
                            "chain_mismatch",
                            "contract_not_deployed",
                            "tracker_registry_mismatch",
                        }:
                            self.recovery_reason = str(error)
                        self.consecutive_failures += 1
                        self.retry_delay_seconds = min(
                            settings.indexer_retry_max_interval,
                            settings.indexer_retry_interval
                            * 2 ** min(self.consecutive_failures - 1, 16),
                        )
                        self.phase = "retrying"
                    self._log_health_transition()
                    if not isinstance(error, (IndexerBusy, ReconciliationRequired)):
                        self.w3 = self.product_registry = self.shipment_tracker = None
                    self._stop_event.wait(self.retry_delay_seconds)
        finally:
            self.running = False
            self.phase = "stopped"

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
        self._check_stopping()
        block = self.w3.eth.get_block(number)
        if block["number"] != number:
            raise ValueError("RPC block number mismatch")
        return _hex(block["hash"])

    def poll_once(self):
        """One atomic batch. Exposed for deterministic integration/recovery checks."""
        self._check_stopping()
        self._observe_head(self.w3.eth.block_number)
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
                self._check_stopping()
                db.commit()
            except Exception:
                db.rollback()
                raise
        # Only published after a successful commit. Reconnecting clients refetch.
        with self._health_lock:
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
                    self._check_stopping()
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
        self._check_stopping()
        args = event["args"]
        try:
            info = contract.functions.getProduct(args["productId"]).call(
                block_identifier=event["blockNumber"]
            )
        except Exception:
            self._check_stopping()
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
        self._check_stopping()
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
            product = (
                db.query(Product)
                .filter_by(product_id=binding.product_id)
                .with_for_update()
                .one()
            )
            self._assign_scope(product, row.product_key)
            return binding, product
        if row.event_type != "ProductRegistered":
            raise ReconciliationRequired("Registration missing before product history")
        try:
            product = find_canonical_product(
                db, row.product_key, settings.chain_id, self.product_registry_address
            )
        except ValueError as error:
            raise ReconciliationRequired(str(error)) from None
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
            for field in ("registered_at", "chain_registered_at"):
                baseline[field] = (
                    baseline[field].isoformat() if baseline[field] else None
                )
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
                    chain_registered_at=None,
                    registration_status="legacy_unreconciled",
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
                chain_registered_at=None,
                registration_status="unregistered",
            )
            product = Product(
                product_id=row.product_key,
                created_at=datetime.now(timezone.utc),
                **dict(
                    baseline,
                    registered_at=datetime.fromisoformat(baseline["registered_at"]),
                ),
            )
            self._assign_scope(product, row.product_key)
            db.add(product)
            db.flush()
        self._assign_scope(product, row.product_key)
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

    def _assign_scope(self, product, key):
        try:
            assign_identity(
                product,
                scope_values(
                    key,
                    chain_id=settings.chain_id,
                    registry=self.product_registry_address,
                    tracker=self.shipment_tracker_address,
                ),
            )
        except ValueError as error:
            raise ReconciliationRequired(str(error)) from None

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
            product.chain_registered_at = product.registered_at
            product.registration_status = "indexed"
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
                        if field in ("registered_at", "chain_registered_at")
                        and value is not None
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
