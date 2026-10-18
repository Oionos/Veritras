"""Real local PostgreSQL write interruption / API restart / replay acceptance.

Only the isolated Compose Hardhat/PostgreSQL stack is accepted. No fault route
is added to the application. Run phases serially via make testing-recovery-check.
"""

import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from web3 import Web3

STATE = Path("/testing-state/recovery.json")
TRIGGER = "veritras_local_recovery_fault"
FUNCTION = "veritras_local_recovery_fault"


def validate_local(environ, manifest):
    db = make_url(environ.get("DATABASE_URL", ""))
    api = environ.get("LOCAL_RECOVERY_API", "http://127.0.0.1:8000")
    rpc = environ.get("SEPOLIA_RPC_URL", "")
    if (
        environ.get("ENVIRONMENT") != "testing"
        or environ.get("CHAIN_ID") != "31337"
        or str(manifest.get("chainId")) != "31337"
    ):
        raise RuntimeError(
            "Recovery drill requires the isolated Hardhat testing environment"
        )
    if (
        db.get_backend_name() not in ("postgres", "postgresql")
        or db.host not in ("postgres", "localhost", "127.0.0.1")
        or db.database != "veritras_test"
    ):
        raise RuntimeError("Recovery drill requires the local veritras_test database")
    for url, hosts in [
        (api, ("backend", "localhost", "127.0.0.1")),
        (rpc, ("blockchain", "localhost", "127.0.0.1")),
    ]:
        parsed = urlparse(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in hosts
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise RuntimeError(
                "Recovery drill refuses hosted or credentialed endpoints"
            )
    return db.set(drivername="postgresql+psycopg2"), api.rstrip("/"), rpc


def request(api, path, body=None, token=None):
    headers = {"Origin": "http://localhost:13000"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(
        api + path,
        headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def wait(predicate, timeout=120):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if predicate():
                return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(1)
    raise RuntimeError("Local recovery acceptance timed out")


def inspect(engine, state):
    with engine.connect() as db:
        product = db.execute(
            text("SELECT metadata_uri FROM products WHERE product_id=:product"),
            {"product": state["product_id"]},
        ).scalar_one()
        checkpoints = db.execute(
            text("SELECT count(*) FROM checkpoints WHERE product_id=:product"),
            {"product": state["product_id"]},
        ).scalar_one()
        journal = (
            db.execute(
                text(
                    "SELECT event_id FROM chain_events WHERE canonical AND transaction_hash IN (:first,:second) ORDER BY event_id"
                ),
                {"first": state["transactions"][0], "second": state["transactions"][1]},
            )
            .scalars()
            .all()
        )
        cursor = db.execute(
            text(
                "SELECT last_processed_block FROM indexer_cursors WHERE chain_id=31337"
            )
        ).scalar_one()
        planning = db.execute(
            text("SELECT notes,status FROM shipments WHERE shipment_id=:shipment"),
            {"shipment": state["shipment_id"]},
        ).one()
    return dict(
        metadata_uri=product,
        checkpoints=checkpoints,
        journal=list(journal),
        cursor=cursor,
        notes=planning.notes,
        status=planning.status,
    )


def assert_rolled_back(engine, state):
    result = inspect(engine, state)
    assert result["metadata_uri"] == "ipfs://recovery-original"
    assert result["checkpoints"] == 1
    assert result["journal"] == []
    assert result["cursor"] < state["block"]
    assert result["notes"] == "Preserve recovery planning" and result["status"] == "0"
    return result


def install_fault(engine, product):
    if not re.fullmatch(r"PROD-[0-9A-F]{8}", product):
        raise RuntimeError("Unexpected local product identity")
    with engine.begin() as db:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        if db.execute(
            text("SELECT count(*) FROM pg_trigger WHERE tgname=:name"),
            {"name": TRIGGER},
        ).scalar_one():
            raise RuntimeError(
                "Finish the previous recovery drill before preparing another"
            )
        db.execute(
            text(
                f"CREATE FUNCTION {FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Controlled local recovery write failure'; END $$"
            )
        )
        db.execute(
            text(
                f"CREATE TRIGGER {TRIGGER} BEFORE INSERT ON checkpoints FOR EACH ROW WHEN (NEW.product_id = '{product}') EXECUTE FUNCTION {FUNCTION}()"
            )
        )


def remove_fault(engine):
    with engine.begin() as db:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text(f"DROP TRIGGER IF EXISTS {TRIGGER} ON checkpoints"))
        db.execute(text(f"DROP FUNCTION IF EXISTS {FUNCTION}()"))


def prepare(engine, api, w3, manifest):
    assert request(api, "/health/ready")[0] == 200
    owner = w3.eth.accounts[0]
    _, challenge = request(api, "/auth/challenge", {"address": owner})
    signed = w3.provider.make_request(
        "personal_sign", ["0x" + challenge["message"].encode().hex(), owner]
    )
    status, session = request(
        api,
        "/auth/verify",
        {"message": challenge["message"], "signature": signed["result"]},
    )
    assert status == 200
    token = session["access_token"]
    status, draft = request(
        api, "/products/", {"name": "Real recovery acceptance"}, token
    )
    assert status == 200
    status, shipment = request(
        api,
        "/shipments/",
        {
            "product_id": draft["product_id"],
            "origin": "Recovery drill factory",
            "destination": "Recovery drill depot",
            "notes": "Preserve recovery planning",
        },
        token,
    )
    assert status == 200
    from app.services.indexer import load_abi

    registry = w3.eth.contract(
        address=Web3.to_checksum_address(manifest["contracts"]["ProductRegistry"]),
        abi=load_abi("ProductRegistry"),
    )
    tracker = w3.eth.contract(
        address=Web3.to_checksum_address(manifest["contracts"]["ShipmentTracker"]),
        abi=load_abi("ShipmentTracker"),
    )
    key = bytes.fromhex(draft["on_chain_product_id"][2:])
    w3.eth.wait_for_transaction_receipt(
        registry.functions.registerProduct(
            key, draft["name"], "Recovery test", "ipfs://recovery-original"
        ).transact({"from": owner})
    )
    w3.eth.wait_for_transaction_receipt(
        tracker.functions.recordCheckpoint(
            key, "Recovery factory", 0, "Before interruption"
        ).transact({"from": owner})
    )
    wait(
        lambda: len(
            request(api, f"/products/{draft['product_id']}")[1].get("history", [])
        )
        == 1
    )
    state = {
        "product_id": draft["product_id"],
        "shipment_id": shipment["shipment_id"],
        "metadata_uri": "ipfs://recovery-" + draft["product_id"].lower(),
    }
    install_fault(engine, draft["product_id"])
    # Keep both events in one block so a metadata write precedes the failed
    # checkpoint in the same indexer transaction, regardless of polling timing.
    try:
        assert (
            w3.provider.make_request("evm_setAutomine", [False]).get("result") is True
        )
        nonce = w3.eth.get_transaction_count(owner)
        first = registry.functions.updateProductMetadata(
            key, state["metadata_uri"]
        ).transact({"from": owner, "nonce": nonce, "gas": 600000})
        second = tracker.functions.recordCheckpoint(
            key, "Recovery route", 1, "After interruption"
        ).transact({"from": owner, "nonce": nonce + 1, "gas": 600000})
        w3.provider.make_request("evm_mine", [])
    except BaseException:
        remove_fault(engine)
        raise
    finally:
        w3.provider.make_request("evm_setAutomine", [True])
    receipts = [w3.eth.wait_for_transaction_receipt(h) for h in (first, second)]
    assert (
        all(r.status == 1 for r in receipts)
        and receipts[0].blockNumber == receipts[1].blockNumber
    )
    state.update(
        block=receipts[0].blockNumber,
        transactions=["0x" + bytes(h).hex() for h in (first, second)],
    )
    STATE.write_text(json.dumps(state))
    wait(
        lambda: request(api, "/health/ready")[0] == 503
        and bool(request(api, "/health/ready")[1]["indexer"]["last_error"])
    )
    assert request(api, "/health/live")[0] == 200
    assert_rolled_back(engine, state)
    print(
        "PASS: real PostgreSQL failure rolled back journal, metadata, checkpoint, shipment and cursor",
        flush=True,
    )


def recover(engine, api):
    state = json.loads(STATE.read_text())
    try:
        # This phase follows a full API process restart with the fault installed.
        wait(
            lambda: request(api, "/health/ready")[0] == 503
            and bool(request(api, "/health/ready")[1]["indexer"]["last_error"])
        )
        assert_rolled_back(engine, state)
    finally:
        remove_fault(engine)
    wait(lambda: request(api, "/health/ready")[0] == 200)
    result = inspect(engine, state)
    assert (
        result["metadata_uri"] == state["metadata_uri"] and result["checkpoints"] == 2
    )
    assert len(result["journal"]) == 2 and len(set(result["journal"])) == 2
    assert result["cursor"] >= state["block"] and result["status"] == "1"
    assert result["notes"] == "Preserve recovery planning"
    state["recovered_events"] = result["journal"]
    STATE.write_text(json.dumps(state))
    print(
        "PASS: restart retained committed progress; repair replayed the interrupted block exactly once",
        flush=True,
    )


def verify(engine, api):
    state = json.loads(STATE.read_text())
    wait(lambda: request(api, "/health/ready")[0] == 200)
    result = inspect(engine, state)
    assert result["checkpoints"] == 2 and result["journal"] == state["recovered_events"]
    assert (
        result["metadata_uri"] == state["metadata_uri"]
        and result["cursor"] >= state["block"]
    )
    status, detail = request(api, f"/products/{state['product_id']}")
    assert status == 200 and len(detail["history"]) == 2
    assert len({cp["id"] for cp in detail["history"]}) == 2
    print(
        "PASS: second API restart preserved recovered canonical evidence without duplicates",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "recover", "verify"])
    args = parser.parse_args()
    manifest = json.loads(Path(os.environ["DEPLOYMENT_MANIFEST"]).read_text())
    url, api, rpc = validate_local(os.environ, manifest)
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 5}))
    if w3.eth.chain_id != 31337:
        raise RuntimeError("RPC is not the isolated Hardhat chain")
    os.environ["PRODUCT_REGISTRY_CONTRACT"] = manifest["contracts"]["ProductRegistry"]
    os.environ["SHIPMENT_TRACKER_CONTRACT"] = manifest["contracts"]["ShipmentTracker"]
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    with engine.connect() as db:
        if any(
            chain != 31337
            for chain in db.execute(
                text("SELECT chain_id FROM indexer_cursors")
            ).scalars()
        ):
            raise RuntimeError("Database contains a non-local chain scope")
    try:
        if args.phase == "prepare":
            prepare(engine, api, w3, manifest)
        elif args.phase == "recover":
            recover(engine, api)
        else:
            verify(engine, api)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
