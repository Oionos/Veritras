"""Real PostgreSQL + fresh worker processes, with a read-only RPC fixture."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from environment_policy import environment


def test_private_replay_survives_two_actual_process_restarts_and_checks_api(tmp_path):
    source = os.environ.get("RECOVERY_TEST_DATABASE_URL")
    if not source:
        pytest.skip("Disposable PostgreSQL recovery databases required")
    source = make_url(source)
    assert (
        source.host in {"localhost", "127.0.0.1"}
        and source.database == "veritras_cicd_source"
    )
    database = "veritras_restore_phasec_integration"
    admin = create_engine(source, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        # Never overwrite/delete a database from an earlier unreviewed attempt.
        assert not connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": database}
        ).scalar()
        connection.execute(text(f"CREATE DATABASE {database}"))
    url = source.set(database=database)
    engine = create_engine(url)
    expected = environment("testing")
    head = expected["start_block"] + expected["confirmations"] + 2
    calls = []

    class RPC(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            method = request["method"]
            calls.append(method)
            result = None
            if method == "web3_clientVersion":
                result = "ReadOnlyRecoveryFixture"
            elif method == "eth_chainId":
                result = hex(expected["chain_id"])
            elif method == "eth_blockNumber":
                result = hex(head)
            elif method == "eth_getCode":
                result = "0x6000"
            elif method == "eth_call":
                result = "0x" + "0" * 24 + expected["registry"][2:].lower()
            elif method == "eth_getLogs":
                result = []
            elif method == "eth_getBlockByNumber":
                number = request["params"][0]
                number = head if number == "latest" else int(number, 16)
                result = {
                    "number": hex(number),
                    "hash": "0x" + hashlib.sha256(str(number).encode()).hexdigest(),
                    "timestamp": hex(1800000000),
                }
            payload = {"jsonrpc": "2.0", "id": request["id"], "result": result}
            if result is None:
                payload = {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "error": {
                        "code": -32601,
                        "message": "Read-only fixture method unavailable",
                    },
                }
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), RPC)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        backend = Path(__file__).resolve().parents[1]
        cfg = Config(str(backend / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend / "alembic"))
        cfg.attributes["configure_logger"] = False
        with engine.begin() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
        manifest = tmp_path / "target.json"
        manifest.write_text(
            json.dumps(
                {
                    "private_rehearsal": True,
                    "branch_id": "br-fixture",
                    "environment": "testing",
                    "candidate_sha": "a" * 40,
                    "target": {
                        "host": url.host,
                        "port": url.port or 5432,
                        "database": database,
                    },
                }
            )
        )
        env = {
            **os.environ,
            "DATABASE_URL": url.render_as_string(hide_password=False),
            "ENVIRONMENT": "testing",
            "CHAIN_ID": str(expected["chain_id"]),
            "PRODUCT_REGISTRY_CONTRACT": expected["registry"],
            "SHIPMENT_TRACKER_CONTRACT": expected["tracker"],
            "INDEXER_START_BLOCK": str(expected["start_block"]),
            "INDEXER_CONFIRMATIONS": "12",
            "SEPOLIA_RPC_URL": f"http://127.0.0.1:{server.server_port}",
            "INDEXER_POLL_INTERVAL": "1",
            "INDEXER_ENABLED": "false",
            "INDEXER_MAX_LAG_BLOCKS": "0",
            "INDEXER_HEAD_STALE_AFTER": "300",
            "JWT_SECRET_KEY": "private-recovery-fixture-key-only-123456789",
            "SIWE_ORIGINS": "https://private-rehearsal.invalid",
            "CORS_ORIGINS": "https://private-rehearsal.invalid",
        }
        results = []
        for index, phase in enumerate(("reconcile", "fixed", "fixed", "fixed", "live")):
            output = tmp_path / f"{index}.json"
            if phase != "reconcile":
                env["INDEXER_ENABLED"] = "true"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(backend / "replay_private_restore.py"),
                    "--phase",
                    phase,
                    "--manifest",
                    str(manifest),
                    "--output",
                    str(output),
                    "--timeout",
                    "30",
                ],
                cwd=backend,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=45,
            )
            result = json.loads(output.read_text())
            assert completed.returncode == 0 and result["passed"], result
            results.append(result)
        assert len({result["snapshot_digest"] for result in results[1:4]}) == 1
        assert results[0]["scan_progress"]["scan_state"] == "complete"
        assert results[0]["scan_progress"]["ranges_completed"] == 1
        assert results[0]["scan_progress"]["last_completed_block"] == head - 12
        assert len({result["journal_prefix_digest"] for result in results[1:]}) == 1
        assert results[-1]["api_reads"]["passed"]
        assert results[-1]["api_reads"]["public_listener"] is False
        assert not any("send" in name.lower() for name in calls)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE {database}"))
        admin.dispose()
