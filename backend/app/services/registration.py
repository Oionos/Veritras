"""Bounded receipt observations. Submission hashes and wallet callbacks are untrusted."""

from datetime import datetime, timezone
from web3 import Web3
from web3.exceptions import TransactionNotFound
from web3.logs import DISCARD
from app.core.config import settings
from app.core.product_id import canonical_product_id
from app.models.chain import ChainEvent
from app.models.registration import RegistrationAttempt
from app.services.indexer import load_abi


def rpc():
    if not settings.sepolia_rpc_url:
        raise ConnectionError("rpc_unavailable")
    w3 = Web3(
        Web3.HTTPProvider(
            settings.sepolia_rpc_url,
            request_kwargs={"timeout": min(settings.indexer_rpc_timeout, 2)},
            exception_retry_configuration=None,
        )
    )
    if w3.eth.chain_id != settings.chain_id:
        raise ConnectionError("chain_unavailable")
    return w3


def latest_attempt(db, product, operation="registration"):
    return (
        db.query(RegistrationAttempt)
        .filter_by(
            product_id=product.product_id,
            chain_id=product.chain_id,
            registry_address=product.registry_address,
            operation=operation,
        )
        .order_by(RegistrationAttempt.id.desc())
        .first()
    )


def observe(product, attempt=None):
    """Return observations without mutating projections, ownership or journal."""
    result = dict(
        status="submitted",
        reason="awaiting_receipt",
        block_number=None,
        block_hash=None,
        observed_confirmations=None,
        nonce=None,
    )
    if (
        product.chain_id != settings.chain_id
        or product.registry_address != settings.product_registry_contract.lower()
    ):
        return dict(result, reason="scope_mismatch", status="failed")
    tx_hash = attempt.tx_hash if attempt else product.tx_hash
    if not tx_hash or len(tx_hash) != 66:
        return dict(result, status="failed", reason="no_registration_evidence")
    w3 = rpc()
    registry = w3.eth.contract(
        address=Web3.to_checksum_address(product.registry_address),
        abi=load_abi("ProductRegistry"),
    )
    operation = attempt.operation if attempt else "registration"
    cancellation = False
    if attempt:
        try:
            transaction = w3.eth.get_transaction(tx_hash)
        except TransactionNotFound:
            return result
        if transaction["from"].lower() != product.manufacturer_address.lower():
            return dict(result, status="failed", reason="transaction_identity_mismatch")
        cancellation = bool(
            attempt.replaces_tx_hash
            and (transaction.get("to") or "").lower() == transaction["from"].lower()
            and transaction["input"] in ("0x", b"")
        )
        if (
            not cancellation
            and (transaction.get("to") or "").lower() != product.registry_address
        ):
            return dict(result, status="failed", reason="transaction_identity_mismatch")
        result["nonce"] = transaction["nonce"]
        expected = attempt.registration_payload or dict(
            name=product.name,
            description=product.description or "",
            metadataURI=product.metadata_uri or "",
        )
        if not cancellation:
            try:
                function, args = registry.decode_function_input(transaction["input"])
                expected_function = (
                    "registerProduct"
                    if operation == "registration"
                    else "updateProductMetadata"
                )
                valid = function.fn_name == expected_function and bytes(
                    args["productId"]
                ) == canonical_product_id(product.on_chain_product_id)
                if operation == "registration":
                    valid = (
                        valid
                        and args["name"] == expected["name"]
                        and args["description"] == expected["description"]
                        and args["metadataURI"] == expected["metadataURI"]
                    )
                else:
                    valid = valid and args["newMetadataURI"] == attempt.metadata_uri
                if not valid:
                    return dict(
                        result, status="failed", reason="transaction_input_mismatch"
                    )
            except (ValueError, KeyError, TypeError):
                return dict(
                    result, status="failed", reason="transaction_input_mismatch"
                )
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
    except TransactionNotFound:
        return result
    result.update(
        block_number=receipt["blockNumber"],
        block_hash=Web3.to_hex(receipt["blockHash"]),
    )
    if bytes(w3.eth.get_block(receipt["blockNumber"])["hash"]) != bytes(
        receipt["blockHash"]
    ):
        return dict(result, reason="receipt_reorganized")
    depth = max(0, w3.eth.block_number - receipt["blockNumber"])
    result["observed_confirmations"] = depth
    if depth < settings.indexer_confirmations:
        return dict(result, status="confirming", reason="awaiting_confirmation_depth")
    if receipt["status"] != 1:
        return dict(result, status="failed", reason="transaction_reverted")
    if cancellation:
        return dict(result, status="failed", reason="transaction_cancelled")
    if (receipt.get("to") or "").lower() != product.registry_address:
        return dict(result, status="failed", reason="wrong_contract")
    if not attempt and receipt["blockNumber"] != product.block_number:
        return dict(result, status="failed", reason="block_mismatch")
    event_type = (
        "ProductRegistered" if operation == "registration" else "ProductMetadataUpdated"
    )
    event = getattr(registry.events, event_type)()
    matching = [
        log
        for log in event.process_receipt(receipt, errors=DISCARD)
        if log["address"].lower() == product.registry_address
        and bytes(log["args"]["productId"])
        == canonical_product_id(product.on_chain_product_id)
        and (
            operation != "registration"
            or (
                log["args"]["manufacturer"].lower()
                == product.manufacturer_address.lower()
                and log["args"]["name"]
                == (expected["name"] if attempt else product.name)
            )
        )
        and (
            operation != "metadata"
            or log["args"]["metadataURI"] == attempt.metadata_uri
        )
    ]
    if len(matching) != 1:
        return dict(
            result,
            status="failed",
            reason=(
                "registration_event_mismatch"
                if operation == "registration"
                else "metadata_event_mismatch"
            ),
        )
    return dict(result, status="indexing", reason="awaiting_indexer")


def indexed_observation(db, product, observation, tx_hash, operation):
    if observation["status"] != "indexing":
        return observation
    binding = product.indexed_state
    if not binding:
        return observation
    event = (
        db.query(ChainEvent)
        .filter_by(
            scope=binding.scope,
            product_key=product.on_chain_product_id,
            transaction_hash=tx_hash,
            block_hash=observation["block_hash"],
            canonical=True,
            event_type=(
                "ProductRegistered"
                if operation == "registration"
                else "ProductMetadataUpdated"
            ),
        )
        .first()
    )
    if event and (
        operation != "registration" or product.registration_status == "indexed"
    ):
        return dict(observation, status="indexed", reason="matching_confirmed_event")
    return observation


def reconcile(db, product, attempt):
    if attempt.replaced_by:
        return
    try:
        observation = observe(product, attempt)
        observation = indexed_observation(
            db, product, observation, attempt.tx_hash, attempt.operation
        )
    except Exception:
        # Keep the last transaction state, exposing loss of evidence independently.
        attempt.reason = "evidence_unavailable"
        attempt.checked_at = datetime.now(timezone.utc)
        return
    for key in ("status", "reason", "nonce", "block_number", "block_hash"):
        setattr(attempt, key, observation[key])
    attempt.checked_at = datetime.now(timezone.utc)


def evidence(db, product):
    attempt = latest_attempt(db, product)
    indexed = product.registration_status == "indexed"
    result = dict(
        status="not_found",
        reason="no_registration_evidence",
        registration_status=product.registration_status,
        chain_id=product.chain_id,
        registry_address=product.registry_address,
        on_chain_product_id=product.on_chain_product_id,
        manufacturer_address=product.manufacturer_address,
        transaction_hash=(
            product.tx_hash if indexed else (attempt.tx_hash if attempt else None)
        ),
        block_number=product.block_number if indexed else None,
        block_hash=None,
        required_confirmations=settings.indexer_confirmations,
        observed_confirmations=None,
    )
    if not indexed and not attempt:
        return result
    selected = None if indexed else attempt
    try:
        observation = observe(product, selected)
        observation = indexed_observation(
            db, product, observation, result["transaction_hash"], "registration"
        )
    except Exception:
        return dict(result, status="unavailable", reason="evidence_unavailable")
    if selected and selected.replaced_by:
        return dict(
            result,
            status="pending",
            reason="transaction_replaced",
            registration_status="replaced",
        )
    state = observation["status"]
    status = "verified" if state == "indexed" else "pending"
    if state == "failed":
        status = (
            "failed"
            if observation["reason"] == "transaction_reverted"
            else "mismatched"
        )
    return dict(
        result,
        status=status,
        reason=observation["reason"],
        registration_status=state,
        block_number=observation["block_number"],
        block_hash=observation["block_hash"],
        observed_confirmations=observation["observed_confirmations"],
    )
