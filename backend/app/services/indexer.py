import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from web3 import Web3
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.product import Product
from app.models.shipment import Checkpoint, CustodyTransfer, Shipment

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
INDEXER_STATE_FILE = Path(settings.indexer_state_path) if settings.indexer_state_path else BACKEND_DIR / "indexer_state.json"

# Status mapping from uint8 to string
STATUS_MAP = {
    0: "0",
    1: "1",
    2: "2",
    3: "3",
}


def bytes32_to_hex(value) -> str:
    """Convert bytes32 to hex string (0x...)."""
    return Web3.to_hex(value)


def timestamp_to_datetime(ts) -> datetime:
    """Convert uint256 timestamp to Python datetime (UTC)."""
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def find_product(db: Session, value):
    """Resolve a recorded bytes32 ID to an existing public/display ID."""
    hex_id = bytes32_to_hex(value)
    candidates = [hex_id]
    try:
        text_id = bytes(value).rstrip(b"\x00").decode("utf-8")
        if text_id:
            candidates.append(text_id)
    except UnicodeDecodeError:
        pass
    matches = db.query(Product).filter(Product.product_id.in_(candidates)).all()
    if len(matches) > 1:
        raise RuntimeError("Conflicting product identities require reconciliation")
    return matches[0] if matches else None


def load_abi(contract_name: str) -> list:
    """Load contract ABI from the bundled abi/ directory inside the backend package."""
    abi_path = BACKEND_DIR / "app" / "abi" / f"{contract_name}.json"
    with open(abi_path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def load_indexer_state() -> Dict:
    """Load the last processed block from the state file."""
    if INDEXER_STATE_FILE.exists():
        with open(INDEXER_STATE_FILE, "r") as f:
            return json.load(f)
    # Use INDEXER_START_BLOCK env var for initial deployment block
    return {"last_processed_block": settings.indexer_start_block}


def save_indexer_state(state: Dict):
    """Save the last processed block to the state file."""
    INDEXER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = INDEXER_STATE_FILE.with_suffix(".tmp")
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(state, f)
    temporary.replace(INDEXER_STATE_FILE)


class EventIndexer:
    """
    Web3.py-based blockchain event indexer for Veritras.
    Polls the configured Ethereum RPC for ProductRegistered, CheckpointRecorded,
    CustodyTransferred, and DeliveryCompleted events, then persists them to the database.
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        product_registry_address: Optional[str] = None,
        shipment_tracker_address: Optional[str] = None,
        poll_interval: Optional[int] = None,
    ):
        self.rpc_url = rpc_url or settings.sepolia_rpc_url
        self.product_registry_address = product_registry_address or settings.product_registry_contract
        self.shipment_tracker_address = shipment_tracker_address or settings.shipment_tracker_contract
        self.poll_interval = poll_interval or settings.indexer_poll_interval

        self.w3: Optional[Web3] = None
        self.product_registry = None
        self.shipment_tracker = None
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.last_error: Optional[str] = None
        self.last_success_at: Optional[str] = None
        self._last_success_monotonic: Optional[float] = None
        self.last_processed_block: Optional[int] = None
        self.chain_head: Optional[int] = None

    def _connect(self):
        """Initialize Web3 connection and contract instances."""
        if not self.rpc_url:
            raise RuntimeError("RPC URL is not configured")
        if not self.product_registry_address or not self.shipment_tracker_address:
            raise RuntimeError("Contract addresses are not configured")

        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": settings.indexer_rpc_timeout}))
        if not self.w3.is_connected():
            raise ConnectionError("RPC connection failed")
        if self.w3.eth.chain_id != settings.chain_id:
            raise RuntimeError("RPC chain ID does not match configured CHAIN_ID")

        product_registry_abi = load_abi("ProductRegistry")
        shipment_tracker_abi = load_abi("ShipmentTracker")

        self.product_registry = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.product_registry_address),
            abi=product_registry_abi,
        )
        self.shipment_tracker = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.shipment_tracker_address),
            abi=shipment_tracker_abi,
        )
        logger.info("Indexer connected to RPC and contracts initialized")

    def start(self):
        """Start the indexer in a background thread."""
        if self.running:
            logger.warning("Indexer is already running")
            return

        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Indexer background thread started")

    def stop(self):
        """Gracefully stop the indexer loop."""
        self.running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=settings.indexer_rpc_timeout + 2)
            logger.info("Indexer stopped")

    def health(self) -> Dict:
        age = None if self._last_success_monotonic is None else time.monotonic() - self._last_success_monotonic
        lag = None if self.chain_head is None or self.last_processed_block is None else max(0, self.chain_head - self.last_processed_block)
        if not self.running or (self._thread is not None and not self._thread.is_alive()):
            status = "stopped"
        elif self.last_error or (age is not None and age > max(settings.indexer_stale_after, self.poll_interval * 3)):
            status = "degraded"
        elif age is None:
            status = "starting"
        else:
            status = "catching_up" if lag else "current"
        return {
            "status": status, "last_processed_block": self.last_processed_block,
            "chain_head": self.chain_head, "lag_blocks": lag,
            "last_success_at": self.last_success_at, "last_error": self.last_error,
            "poll_interval_seconds": self.poll_interval,
            "chain_id": settings.chain_id,
        }

    def _run(self):
        """Retry startup/polls with bounded ranges and interruptible shutdown."""
        last_processed = None
        while not self._stop_event.is_set():
            try:
                if self.product_registry is None or self.shipment_tracker is None:
                    self._connect()
                if last_processed is None:
                    last_processed = int(load_indexer_state().get("last_processed_block", settings.indexer_start_block))
                latest_block = self.w3.eth.block_number
                self.chain_head = latest_block
                if last_processed > latest_block:
                    raise RuntimeError("Indexer cursor is ahead of chain; reconcile/reset the testing stack")
                from_block = last_processed + 1
                to_block = min(latest_block, last_processed + settings.indexer_batch_size)

                if from_block <= to_block:
                    logger.info("Indexing blocks %s to %s", from_block, to_block)

                # Fetch ProductRegistered events
                product_events = [] if from_block > to_block else self.product_registry.events.ProductRegistered().get_logs(
                    from_block=from_block, to_block=to_block)
                for event in product_events:
                    self._process_product_registered(event)

                # Fetch CheckpointRecorded events
                checkpoint_events = [] if from_block > to_block else self.shipment_tracker.events.CheckpointRecorded().get_logs(
                    from_block=from_block, to_block=to_block)
                for event in checkpoint_events:
                    self._process_checkpoint_recorded(event)

                # Fetch CustodyTransferred events
                custody_events = [] if from_block > to_block else self.shipment_tracker.events.CustodyTransferred().get_logs(
                    from_block=from_block, to_block=to_block)
                for event in custody_events:
                    self._process_custody_transferred(event)

                # Fetch DeliveryCompleted events
                delivery_events = [] if from_block > to_block else self.shipment_tracker.events.DeliveryCompleted().get_logs(
                    from_block=from_block, to_block=to_block)
                for event in delivery_events:
                    self._process_delivery_completed(event)

                save_indexer_state({"last_processed_block": to_block})
                last_processed = to_block
                self.last_processed_block = last_processed
                self.last_success_at = datetime.now(timezone.utc).isoformat()
                self._last_success_monotonic = time.monotonic()
                self.last_error = None
                if last_processed >= latest_block:
                    self._stop_event.wait(self.poll_interval)

            except Exception as e:
                self.last_error = type(e).__name__
                logger.error("Indexer startup/poll failed: %s", self.last_error)
                self.product_registry = None
                self.shipment_tracker = None
                self._stop_event.wait(settings.indexer_retry_interval)
        self.running = False

    def _process_product_registered(self, event: Dict):
        """Persist a ProductRegistered event to the database."""
        args = event["args"]
        product_id = bytes32_to_hex(args["productId"])
        manufacturer = args["manufacturer"]
        name = args["name"]
        timestamp = timestamp_to_datetime(args["timestamp"])
        block_number = event["blockNumber"]
        tx_hash = Web3.to_hex(event["transactionHash"])

        db = SessionLocal()
        try:
            existing = find_product(db, args["productId"])

            # Try to fetch additional product info from the contract
            description = ""
            metadata_uri = ""
            try:
                product_info = self.product_registry.functions.getProduct(args["productId"]).call()
                description = product_info[3] if len(product_info) > 3 else ""
                metadata_uri = product_info[4] if len(product_info) > 4 else ""
            except Exception as e:
                logger.warning(f"Could not fetch product details for {product_id}: {e}")

            values = dict(
                product_id=product_id,
                name=name,
                description=description or None,
                metadata_uri=metadata_uri or None,
                manufacturer_address=manufacturer,
                owner_address=manufacturer.lower(),
                ownership_source="chain_event",
                registered_at=timestamp,
                block_number=block_number,
                tx_hash=tx_hash,
            )
            if existing:
                values.pop("product_id")
                for key, value in values.items():
                    setattr(existing, key, value)
            else:
                db.add(Product(**values))
            db.commit()
            logger.info(f"Indexed ProductRegistered: {product_id}")
        except Exception as e:
            db.rollback()
            logger.error(f"Error processing ProductRegistered: {e}")
            raise
        finally:
            db.close()

    def _history_event_id(self, event: Dict) -> str:
        """Identify a log across restarts; a transaction can contain many logs."""
        address = event.get("address", self.shipment_tracker_address)
        log_index = event.get("logIndex")
        if not Web3.is_address(address) or type(log_index) is not int or log_index < 0:
            raise ValueError("History event requires its emitter and log index")
        return f"{settings.chain_id}:{address.lower()}:{Web3.to_hex(event['transactionHash']).lower()}:{log_index}"

    def _process_checkpoint_recorded(self, event: Dict):
        """Persist a CheckpointRecorded event to the database."""
        args = event["args"]
        product_id = bytes32_to_hex(args["productId"])
        location = args["location"]
        status = STATUS_MAP.get(args["status"], str(args["status"]))
        handler = args["handler"]
        timestamp = timestamp_to_datetime(args["timestamp"])
        notes = args.get("notes", "")
        block_number = event["blockNumber"]
        tx_hash = Web3.to_hex(event["transactionHash"])
        source_event_id = self._history_event_id(event)

        db = SessionLocal()
        try:
            if db.query(Checkpoint).filter(Checkpoint.source_event_id == source_event_id).first():
                return
            product = find_product(db, args["productId"])
            if product:
                product_id = product.product_id
            checkpoint = Checkpoint(
                product_id=product_id,
                location=location,
                status=status,
                handler_address=handler,
                notes=notes or None,
                timestamp=timestamp,
                block_number=block_number,
                tx_hash=tx_hash,
                source_event_id=source_event_id,
            )
            db.add(checkpoint)
            for shipment in db.query(Shipment).filter(Shipment.product_id == product_id).all():
                shipment.status = status
            db.commit()
            logger.info(f"Indexed CheckpointRecorded: {product_id} at {location}")
        except IntegrityError:
            db.rollback()
            # Overlapping deploys can observe the same log. The unique index
            # makes the checkpoint and its shipment update commit once.
            if not db.query(Checkpoint).filter(Checkpoint.source_event_id == source_event_id).first():
                raise
        except Exception as e:
            db.rollback()
            logger.error(f"Error processing CheckpointRecorded: {e}")
            raise
        finally:
            db.close()

    def _process_custody_transferred(self, event: Dict):
        """Persist a CustodyTransferred event to the database."""
        args = event["args"]
        product_id = bytes32_to_hex(args["productId"])
        from_addr = args["from"]
        to_addr = args["to"]
        timestamp = timestamp_to_datetime(args["timestamp"])
        block_number = event["blockNumber"]
        tx_hash = Web3.to_hex(event["transactionHash"])
        source_event_id = self._history_event_id(event)

        db = SessionLocal()
        try:
            if db.query(CustodyTransfer).filter(CustodyTransfer.source_event_id == source_event_id).first():
                return
            product = find_product(db, args["productId"])
            if product:
                product_id = product.product_id
            transfer = CustodyTransfer(
                product_id=product_id,
                from_address=from_addr,
                to_address=to_addr,
                timestamp=timestamp,
                block_number=block_number,
                tx_hash=tx_hash,
                source_event_id=source_event_id,
            )
            db.add(transfer)
            db.commit()
            logger.info(f"Indexed CustodyTransferred: {product_id} from {from_addr} to {to_addr}")
        except IntegrityError:
            db.rollback()
            if not db.query(CustodyTransfer).filter(CustodyTransfer.source_event_id == source_event_id).first():
                raise
        except Exception as e:
            db.rollback()
            logger.error(f"Error processing CustodyTransferred: {e}")
            raise
        finally:
            db.close()

    def _process_delivery_completed(self, event: Dict):
        # A Delivered checkpoint emits both events. CheckpointRecorded already
        # stores the actual location, notes, and status; never invent a second row.
        logger.info("DeliveryCompleted observed at block %s", event["blockNumber"])
